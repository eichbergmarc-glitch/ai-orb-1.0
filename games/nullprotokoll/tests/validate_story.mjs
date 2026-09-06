import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const read = (name) => JSON.parse(fs.readFileSync(path.join(root, "data", name), "utf8"));
const items = read("items.json");
const recipes = read("recipes.json").recipes;
const dialogues = read("dialogues.json");
const prologue = read("prologue.json");
const locations = prologue.locations;
const endings = prologue.endings;

const failures = [];
const check = (condition, message) => {
  if (!condition) failures.push(message);
};

check(Object.keys(locations).length >= 5, "Mindestens fünf Schauplätze erforderlich.");
check(Object.keys(items).length >= 10, "Mindestens zehn Gegenstände erforderlich.");
check(recipes.length >= 4, "Mindestens vier Kombinationsrätsel erforderlich.");
check(Object.keys(endings).length >= 3, "Mindestens drei Prologausgänge erforderlich.");
check(prologue.meta.target_minutes === "30–45", "Zielspielzeit muss als 30–45 Minuten dokumentiert sein.");

const expectedLocations = [
  "krankenstation",
  "diagnostiklabor",
  "sicherheitsrotunde",
  "wartungsgalerie",
  "quarantaene",
  "kaltarchiv",
  "relaiskern"
];
for (const id of expectedLocations) check(Boolean(locations[id]), `Schauplatz fehlt: ${id}`);

const allItemRefs = new Set();
const allEndingRefs = new Set();
const collectEffects = (effects = {}) => {
  for (const key of ["add_items", "remove_items"]) {
    for (const id of effects[key] ?? []) allItemRefs.add(id);
  }
  if (effects.ending) allEndingRefs.add(effects.ending);
};

const graph = new Map(Object.keys(locations).map((id) => [id, []]));
for (const [locationId, location] of Object.entries(locations)) {
  check(Array.isArray(location.hotspots) && location.hotspots.length >= 3, `${locationId}: mindestens drei untersuchbare Objekte erforderlich.`);
  check(Array.isArray(location.exits) && location.exits.length >= 1, `${locationId}: mindestens ein Ausgang erforderlich.`);
  const hotspotIds = new Set();
  for (const hotspot of location.hotspots ?? []) {
    check(Boolean(hotspot.id), `${locationId}: Hotspot ohne ID.`);
    check(!hotspotIds.has(hotspot.id), `${locationId}: doppelte Hotspot-ID ${hotspot.id}.`);
    hotspotIds.add(hotspot.id);
    if (hotspot.dialogue) check(Boolean(dialogues[hotspot.dialogue]), `${locationId}/${hotspot.id}: unbekannter Dialog ${hotspot.dialogue}.`);
    collectEffects(hotspot.effects);
    for (const choice of hotspot.choices ?? []) {
      check(Boolean(choice.id) && Boolean(choice.label) && Boolean(choice.text), `${locationId}/${hotspot.id}: unvollständige Entscheidung.`);
      collectEffects(choice.effects);
    }
    for (const [itemId, use] of Object.entries(hotspot.item_uses ?? {})) {
      allItemRefs.add(itemId);
      collectEffects(use.effects);
    }
  }
  for (const event of location.random_events ?? []) collectEffects(event.effects);
  for (const exit of location.exits ?? []) {
    check(Boolean(locations[exit.to]), `${locationId}: Ausgang ${exit.id} verweist auf unbekannten Ort ${exit.to}.`);
    if (locations[exit.to]) graph.get(locationId).push(exit.to);
    collectEffects(exit.effects);
  }
  collectEffects(location.entry_effects);
}

for (const [dialogueId, dialogue] of Object.entries(dialogues)) {
  check(Boolean(dialogue.nodes?.[dialogue.start]), `${dialogueId}: Startknoten fehlt.`);
  for (const [nodeId, node] of Object.entries(dialogue.nodes ?? {})) {
    check(Boolean(node.speaker) && Boolean(node.text), `${dialogueId}/${nodeId}: Sprecher oder Text fehlt.`);
    check(Array.isArray(node.options) && node.options.length > 0, `${dialogueId}/${nodeId}: Dialogknoten ohne Antwort.`);
    for (const option of node.options ?? []) {
      if (option.next) check(Boolean(dialogue.nodes[option.next]), `${dialogueId}/${nodeId}: unbekannter Folgeknoten ${option.next}.`);
      check(Boolean(option.end) || Boolean(option.next), `${dialogueId}/${nodeId}/${option.id}: weder Ende noch Folgeknoten.`);
      collectEffects(option.effects);
    }
  }
}

const speakers = new Set(
  Object.values(dialogues).flatMap((dialogue) => Object.values(dialogue.nodes).map((node) => node.speaker))
);
check([...speakers].some((name) => name.includes("MIRA")), "MIRA fehlt als zentrale Figur.");
check([...speakers].some((name) => name.includes("Juna")), "Juna fehlt als zentrale Figur.");
check([...speakers].some((name) => name.includes("Samir")), "Samir fehlt als zentrale Figur.");

for (const recipe of recipes) {
  check(Array.isArray(recipe.inputs) && recipe.inputs.length === 2, `${recipe.id}: Rezept braucht genau zwei Eingaben.`);
  check(Boolean(items[recipe.result]), `${recipe.id}: Ergebnis ${recipe.result} ist nicht definiert.`);
  for (const id of recipe.inputs ?? []) check(Boolean(items[id]), `${recipe.id}: Eingabe ${id} ist nicht definiert.`);
}
for (const id of allItemRefs) check(Boolean(items[id]), `Story verweist auf unbekannten Gegenstand ${id}.`);
for (const id of allEndingRefs) check(Boolean(endings[id]), `Story verweist auf unbekanntes Ende ${id}.`);

const reached = new Set([prologue.meta.start_location]);
const queue = [prologue.meta.start_location];
while (queue.length) {
  const from = queue.shift();
  for (const to of graph.get(from) ?? []) {
    if (!reached.has(to)) {
      reached.add(to);
      queue.push(to);
    }
  }
}
for (const id of Object.keys(locations)) check(reached.has(id), `Schauplatz ist im Ortsgraph nicht erreichbar: ${id}`);

const clone = (value) => structuredClone(value);
const makeState = (stats = { logic: 1, empathy: 3, instinct: 2 }) => ({
  flags: [],
  inventory: [],
  puzzles: [],
  stats,
  ending: ""
});
const addUnique = (list, value) => { if (!list.includes(value)) list.push(value); };
const apply = (state, effects = {}) => {
  for (const flag of effects.add_flags ?? []) addUnique(state.flags, flag);
  for (const flag of effects.remove_flags ?? []) state.flags = state.flags.filter((value) => value !== flag);
  for (const id of effects.add_items ?? []) addUnique(state.inventory, id);
  for (const id of effects.remove_items ?? []) state.inventory = state.inventory.filter((value) => value !== id);
  for (const id of effects.solve_puzzles ?? []) addUnique(state.puzzles, id);
  if (effects.ending) state.ending = effects.ending;
};
const meets = (state, conditions = {}) =>
  (conditions.flags_all ?? []).every((id) => state.flags.includes(id)) &&
  (conditions.flags_none ?? []).every((id) => !state.flags.includes(id)) &&
  (conditions.items_all ?? []).every((id) => state.inventory.includes(id)) &&
  (conditions.items_none ?? []).every((id) => !state.inventory.includes(id)) &&
  Object.entries(conditions.stats_min ?? {}).every(([key, value]) => state.stats[key] >= value);
const hotspot = (locationId, hotspotId) => locations[locationId].hotspots.find((entry) => entry.id === hotspotId);
const useHotspot = (state, locationId, hotspotId) => apply(state, hotspot(locationId, hotspotId).effects);
const chooseHotspot = (state, locationId, hotspotId, choiceId) => {
  const choice = hotspot(locationId, hotspotId).choices.find((entry) => entry.id === choiceId);
  check(Boolean(choice), `Simulation: Entscheidung ${locationId}/${hotspotId}/${choiceId} fehlt.`);
  check(meets(state, choice?.conditions), `Simulation: Bedingung für ${choiceId} ist nicht erfüllt.`);
  apply(state, choice?.effects);
};
const useItem = (state, locationId, hotspotId, itemId) => {
  const use = hotspot(locationId, hotspotId).item_uses?.[itemId];
  check(Boolean(use), `Simulation: Nutzung ${itemId} an ${locationId}/${hotspotId} fehlt.`);
  check(meets(state, use?.conditions), `Simulation: Bedingung für Nutzung ${itemId} an ${hotspotId} ist nicht erfüllt.`);
  apply(state, use?.effects);
};
const combine = (state, first, second) => {
  const recipe = recipes.find((entry) => entry.inputs.includes(first) && entry.inputs.includes(second));
  check(Boolean(recipe), `Simulation: Rezept ${first} + ${second} fehlt.`);
  check(state.inventory.includes(first) && state.inventory.includes(second), `Simulation: Zutaten für ${first} + ${second} fehlen.`);
  state.inventory = state.inventory.filter((id) => id !== first && id !== second);
  addUnique(state.inventory, recipe.result);
  addUnique(state.puzzles, recipe.puzzle_id);
};
const dialogueChoice = (state, dialogueId, nodeId, optionId) => {
  const option = dialogues[dialogueId].nodes[nodeId].options.find((entry) => entry.id === optionId);
  check(Boolean(option), `Simulation: Dialogoption ${dialogueId}/${nodeId}/${optionId} fehlt.`);
  check(meets(state, option?.conditions), `Simulation: Dialogbedingung ${dialogueId}/${optionId} ist nicht erfüllt.`);
  apply(state, option?.effects);
};

const sandboxPath = makeState();
useHotspot(sandboxPath, "krankenstation", "treatment_bed");
useHotspot(sandboxPath, "krankenstation", "medical_cabinet");
combine(sandboxPath, "badge_cracked", "film_conductive");
useItem(sandboxPath, "krankenstation", "sealed_door", "badge_repaired");
useHotspot(sandboxPath, "diagnostiklabor", "radio_case");
useHotspot(sandboxPath, "wartungsgalerie", "emergency_lamp");
useHotspot(sandboxPath, "wartungsgalerie", "warning_beacon");
useHotspot(sandboxPath, "wartungsgalerie", "tool_wall");
useHotspot(sandboxPath, "wartungsgalerie", "broken_speaker");
useHotspot(sandboxPath, "wartungsgalerie", "parts_cabinet");
combine(sandboxPath, "cell_empty", "capacitor_charged");
combine(sandboxPath, "fiber_cord", "speaker_magnet");
combine(sandboxPath, "radio_broken", "crypto_module");
dialogueChoice(sandboxPath, "samir_secure", "plan_node", "end_plan");
useItem(sandboxPath, "sicherheitsrotunde", "floor_grate", "retrieval_line");
useItem(sandboxPath, "sicherheitsrotunde", "manual_distributor", "bridge_cell");
chooseHotspot(sandboxPath, "sicherheitsrotunde", "power_priority", "archive_first");
dialogueChoice(sandboxPath, "juna_first", "glass", "release_now");
useHotspot(sandboxPath, "kaltarchiv", "audit_core_intact");
useHotspot(sandboxPath, "kaltarchiv", "rack_marks");
useHotspot(sandboxPath, "kaltarchiv", "mirror_compartment");
combine(sandboxPath, "isolation_token", "mirror_module");
check(sandboxPath.flags.includes("juna_resolved") && sandboxPath.flags.includes("audit_secured"), "Simulation: Relaiskern bleibt im Sandbox-Pfad gesperrt.");
check(sandboxPath.inventory.includes("sandbox_bridge") && sandboxPath.flags.includes("secure_channel") && sandboxPath.flags.includes("juna_free"), "Simulation: verborgener vierter Ausgang wird nicht freigeschaltet.");
chooseHotspot(sandboxPath, "relaiskern", "final_console", "sandbox_mira");
check(sandboxPath.ending === "sandbox_mira", "Simulation: Sandbox-Ende wurde nicht erreicht.");

const lowStatPath = makeState({ logic: 1, empathy: 1, instinct: 1 });
useHotspot(lowStatPath, "krankenstation", "treatment_bed");
useHotspot(lowStatPath, "krankenstation", "medical_cabinet");
combine(lowStatPath, "badge_cracked", "film_conductive");
useItem(lowStatPath, "krankenstation", "sealed_door", "badge_repaired");
useHotspot(lowStatPath, "wartungsgalerie", "emergency_lamp");
useHotspot(lowStatPath, "wartungsgalerie", "warning_beacon");
useHotspot(lowStatPath, "wartungsgalerie", "tool_wall");
useHotspot(lowStatPath, "wartungsgalerie", "broken_speaker");
combine(lowStatPath, "cell_empty", "capacitor_charged");
combine(lowStatPath, "fiber_cord", "speaker_magnet");
useItem(lowStatPath, "sicherheitsrotunde", "floor_grate", "retrieval_line");
useItem(lowStatPath, "sicherheitsrotunde", "manual_distributor", "bridge_cell");
chooseHotspot(lowStatPath, "sicherheitsrotunde", "power_priority", "quarantine_first");
dialogueChoice(lowStatPath, "juna_first", "glass", "keep_locked");
useHotspot(lowStatPath, "kaltarchiv", "audit_core_partial");
check(lowStatPath.flags.includes("juna_resolved") && lowStatPath.flags.includes("audit_secured"), "Simulation: Pflichtweg ist mit allen Eigenschaften auf 1 nicht lösbar.");

const baseEndings = hotspot("relaiskern", "final_console").choices.filter((choice) => !choice.conditions);
check(baseEndings.length >= 3, "Die Schlussentscheidung muss drei bedingungslos verfügbare Ausgänge enthalten.");
for (const choice of baseEndings) {
  const state = clone(sandboxPath);
  state.ending = "";
  apply(state, choice.effects);
  check(Boolean(endings[state.ending]), `Grundausgang ${choice.id} führt zu keinem definierten Ende.`);
}

// --- Sprache, Ton und Zwischensequenzen -------------------------------------

const cutscenePath = path.join(root, "data", "cutscenes.json");
check(fs.existsSync(cutscenePath), "cutscenes.json fehlt.");
let cutsceneCount = 0;
if (fs.existsSync(cutscenePath)) {
  const sequences = JSON.parse(fs.readFileSync(cutscenePath, "utf8")).sequences ?? {};
  cutsceneCount = Object.keys(sequences).length;
  check(Boolean(sequences.prolog_start), "Zwischensequenz prolog_start fehlt.");
  for (const endingId of Object.keys(endings)) {
    check(Boolean(sequences[`ende_${endingId}`]), `Zwischensequenz fehlt für Ende: ${endingId}`);
  }
  for (const [id, beats] of Object.entries(sequences)) {
    check(Array.isArray(beats) && beats.length > 0, `Zwischensequenz ohne Inhalt: ${id}`);
    for (const beat of beats ?? []) {
      check(Boolean(beat.text?.trim()), `Zwischensequenz ${id}: Beat ohne Text.`);
      if (beat.background) {
        check(
          fs.existsSync(path.join(root, "assets", "backgrounds", `${beat.background}.png`)),
          `Zwischensequenz ${id}: Hintergrund fehlt: ${beat.background}`
        );
      }
    }
  }
}

const requiredSfx = [
  "item_pickup", "device_use", "comm_open", "door_move", "inspect",
  "ui_click", "ui_confirm", "voice_listen_start", "voice_listen_stop",
  "voice_fail", "event_sting"
];
let audioCount = 0;
for (const id of expectedLocations) {
  const ambience = path.join(root, "assets", "audio", "ambience", `${id}.ogg`);
  check(fs.existsSync(ambience), `Raumatmosphäre fehlt: ${id}.ogg`);
  if (fs.existsSync(ambience)) audioCount += 1;
}
for (const id of requiredSfx) {
  const effect = path.join(root, "assets", "audio", "sfx", `${id}.ogg`);
  check(fs.existsSync(effect), `Effektgeräusch fehlt: ${id}.ogg`);
  if (fs.existsSync(effect)) audioCount += 1;
}

if (failures.length) {
  console.error(`Storyprüfung fehlgeschlagen (${failures.length}):`);
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log("NULLPROTOKOLL – Storyprüfung bestanden");
console.log(`  Schauplätze: ${Object.keys(locations).length}`);
console.log(`  Dialoge: ${Object.keys(dialogues).length} (${speakers.size} Sprecherbezeichnungen)`);
console.log(`  Gegenstände: ${Object.keys(items).length}`);
console.log(`  Kombinationen: ${recipes.length}`);
console.log(`  Prologausgänge: ${Object.keys(endings).length}`);
console.log("  Simulierter Pfad: Start → vier Kernrätsel → Juna frei → intaktes Audit → Sandbox-Ende");
console.log("  Niedrigwert-Pfad: alle Eigenschaften 1 → Juna eingeschlossen → Teil-Audit → Relaiskern");
console.log(`  Zwischensequenzen: ${cutsceneCount}`);
console.log(`  Klangdateien: ${audioCount}`);
