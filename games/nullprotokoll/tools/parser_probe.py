#!/usr/bin/env python3
"""Nachbildung von scripts/core/command_parser.gd zum Prüfen der Grammatik.

Dies ist ein Werkzeug, kein Teil des Spiels. Es bildet die Erkennungslogik in
Python nach, damit sich Formulierungen ohne laufende Godot-Instanz durchspielen
lassen. Weicht das Verhalten hier vom Spiel ab, ist diese Datei falsch – die
Wahrheit steht in der GDScript-Fassung.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ACCEPT = 0.52
STRONG = 0.78

NUMBER_WORDS = {
    "null": 0, "eins": 1, "eine": 1, "einen": 1, "erste": 1, "ersten": 1, "erstes": 1,
    "zwei": 2, "zweite": 2, "zweiten": 2, "zweites": 2,
    "drei": 3, "dritte": 3, "dritten": 3, "drittes": 3,
    "vier": 4, "vierte": 4, "vierten": 4, "viertes": 4,
    "fuenf": 5, "fünf": 5, "fuenfte": 5, "fünfte": 5, "fuenften": 5, "fünften": 5,
    "sechs": 6, "sechste": 6, "sechsten": 6,
    "sieben": 7, "siebte": 7, "siebten": 7,
    "acht": 8, "achte": 8, "achten": 8,
    "neun": 9, "neunte": 9, "neunten": 9,
    "zehn": 10, "zehnte": 10, "zehnten": 10,
}

FILLERS = [
    "bitte", "mal", "doch", "jetzt", "sofort", "dann", "hier", "da", "dort",
    "dich", "dir", "mich", "mir", "ich", "du", "wir", "es", "der", "die", "das",
    "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "zum", "zur",
    "zu", "nach", "in", "ins", "im", "an", "am", "auf", "aufs", "bei", "beim",
    "und", "mit", "vom", "von", "fuer", "für", "ueber", "über", "nochmal", "noch",
    "kannst", "kann", "wuerdest", "würdest", "wuerde", "würde", "soll", "sollst",
    "lass", "uns", "einfach", "gerne", "gern",
]

PATTERNS = [
    ("combine", ["kombiniere", "kombinieren", "verbinde", "verbinden", "setze zusammen", "baue zusammen"]),
    ("use_item", ["benutze den", "benutze die", "benutze das", "verwende den", "verwende die", "verwende das", "setze ein", "wende an"]),
    ("move", ["bewege dich", "beweg dich", "bewege mich", "geh zum", "geh zur", "geh zu", "gehe zum", "gehe zur", "gehe zu", "lauf zum", "lauf zur", "lauf zu", "laufe zu", "geh rueber", "geh hinueber", "geh in", "gehe in", "tritt an", "stell dich"]),
    ("look_around", ["sieh dich um", "schau dich um", "umsehen", "was sehe ich", "beschreibe den raum", "wo bin ich"]),
    ("hints", ["zeige objekte", "zeig objekte", "was kann ich benutzen", "zeige hinweise", "zeig mir die objekte", "objekte zeigen", "markiere objekte"]),
    ("interact", ["oeffne", "öffne", "mach auf", "schliesse auf", "schließe auf", "nimm", "nehme", "hebe auf", "heb auf", "untersuche", "untersuch", "betrachte", "sieh dir", "schau dir", "sieh an", "schau an", "sieh", "schau", "lies", "durchsuche", "such", "suche", "druecke", "drücke", "drueck", "drück", "ziehe", "zieh", "betaetige", "betätige", "aktiviere", "schalte", "rede mit", "sprich mit", "sprechen mit", "frage", "benutze", "verwende", "repariere", "beruehre", "berühre"]),
    ("inventory", ["inventar", "tasche", "was habe ich", "zeige inventar", "gegenstaende", "gegenstände"]),
    ("journal", ["journal", "tagebuch", "notizen", "aufzeichnungen", "ziele"]),
    ("status", ["status", "charakter", "eigenschaften", "werte"]),
    ("menu", ["menue", "menü", "pause", "hauptmenue", "hauptmenü"]),
    ("save", ["speichere", "speichern", "sicherung", "spielstand speichern"]),
    ("load", ["lade spielstand", "laden", "letzten spielstand"]),
    ("close", ["schliessen", "schließen", "zurueck", "zurück", "abbrechen", "beenden das fenster", "raus"]),
    ("repeat", ["wiederhole", "nochmal sagen", "was war das", "sag das nochmal", "wiederholen"]),
    ("stop_voice", ["sei still", "ruhe", "still", "hoer auf zu reden", "hör auf zu reden", "schweig"]),
    ("choose", ["antworte", "antwort", "option", "waehle", "wähle", "entscheide", "nimm option", "sag"]),
    ("help", ["was kann ich sagen", "hilfe", "befehle", "welche befehle"]),
]

DIRECTIONS = {
    "links": "links", "linke": "links", "nach links": "links",
    "rechts": "rechts", "rechte": "rechts", "nach rechts": "rechts",
    "vor": "vor", "vorne": "vor", "vorwaerts": "vor", "vorwärts": "vor", "nach vorne": "vor",
    "zurueck": "zurueck", "zurück": "zurueck", "rueckwaerts": "zurueck", "rückwärts": "zurueck",
}


def normalize(text: str) -> str:
    cleaned = re.sub(r"[.,!?;:\"'„“”\-–()\n\t]", " ", text.lower())
    while "  " in cleaned:
        cleaned = cleaned.replace("  ", " ")
    return cleaned.strip()


def fold(text: str) -> str:
    return (text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            .replace("ß", "ss").replace("é", "e").replace("è", "e"))


def detect_intent(normalized: str):
    folded = fold(normalized)
    best = ("unknown", "", -1)
    for intent, phrases in PATTERNS:
        for phrase_raw in phrases:
            phrase = fold(phrase_raw)
            position = folded.find(phrase)
            if position < 0:
                continue
            if best[2] < 0 or position < best[2] or (position == best[2] and len(phrase) > len(best[1])):
                best = (intent, phrase, position)
        if best[2] == 0:
            break
    if best[2] < 0:
        return "unknown", normalized
    remainder = folded[: best[2]] + " " + folded[best[2] + len(best[1]):]
    return best[0], remainder.strip()


def strip_fillers(text: str) -> str:
    folded_fillers = {fold(f) for f in FILLERS}
    return " ".join(w for w in fold(text).split() if w and w not in folded_fillers)


def edit_distance(left: str, right: str) -> int:
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for row in range(1, len(left) + 1):
        current = [row] + [0] * len(right)
        for column in range(1, len(right) + 1):
            cost = 0 if left[row - 1] == right[column - 1] else 1
            current[column] = min(current[column - 1] + 1, previous[column] + 1, previous[column - 1] + cost)
        previous = current
    return previous[len(right)]


def similarity(spoken: str, candidate: str) -> float:
    left, right = fold(spoken).strip(), fold(candidate).strip()
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_tokens, right_tokens = left.split(), right.split()
    matched = 0
    for spoken_token in left_tokens:
        if len(spoken_token) < 3:
            continue
        for candidate_token in right_tokens:
            if len(candidate_token) < 3:
                continue
            if candidate_token in spoken_token or spoken_token in candidate_token:
                matched += 1
                break
            if edit_distance(spoken_token, candidate_token) <= 1:
                matched += 1
                break
    significant = sum(1 for t in left_tokens if len(t) >= 3)
    containment = matched / significant if significant else 0.0
    closeness = 1.0 - edit_distance(left, right) / max(len(left), len(right), 1)
    return max(0.0, min(1.0, containment * 0.72 + closeness * 0.28))


def id_words(identifier: str) -> str:
    return identifier.replace("_", " ").replace("-", " ")


def best_target(phrase: str, context: dict):
    if not phrase.strip():
        return None
    best, best_score = None, 0.0
    for kind in ("hotspots", "exits"):
        for entry in context.get(kind, []):
            score = similarity(phrase, entry.get("label", ""))
            score = max(score, similarity(phrase, id_words(entry.get("id", ""))) * 0.92)
            if score > best_score:
                best_score = score
                best = {"kind": "hotspot" if kind == "hotspots" else "exit",
                        "id": entry.get("id", ""), "label": entry.get("label", ""), "score": score}
    return best if best_score >= ACCEPT else None


def best_item(phrase: str, context: dict):
    if not phrase.strip():
        return None
    best, best_score = None, 0.0
    for entry in context.get("items", []):
        label = entry.get("name", entry.get("label", ""))
        score = max(similarity(phrase, label), similarity(phrase, id_words(entry.get("id", ""))) * 0.92)
        if score > best_score:
            best_score = score
            best = {"id": entry.get("id", ""), "label": label, "score": score}
    return best if best_score >= ACCEPT else None


def direction_in(phrase: str) -> str:
    folded = fold(phrase)
    for key, value in DIRECTIONS.items():
        k = fold(key)
        if folded == k or folded.startswith(k + " ") or folded.endswith(" " + k):
            return value
    return ""


def ordinal_in(phrase: str) -> int:
    for word in fold(phrase).split():
        if word.isdigit():
            return int(word)
        for key, value in NUMBER_WORDS.items():
            if fold(key) == word:
                return value
    return 0


def split_connector(text: str):
    folded = fold(text)
    for connector in (" mit ", " auf ", " aufs ", " an ", " am ", " ans ", " in ", " im ",
                      " ins ", " gegen ", " bei ", " beim ", " zum ", " zur ", " durch "):
        position = folded.find(connector)
        if position > 0:
            return folded[:position], folded[position + len(connector):]
    return folded, ""


def parse(raw: str, context: dict) -> dict:
    normalized = normalize(raw)
    if not normalized:
        return {"intent": "unknown"}
    intent, remainder = detect_intent(normalized)

    if intent == "combine":
        first_part, second_part = split_connector(remainder)
        first = best_item(strip_fillers(first_part), context)
        second = best_item(strip_fillers(second_part), context)
        if not first or not second:
            return {"intent": "unknown", "reason": "kombination_unklar"}
        return {"intent": "combine", "item": first["id"], "secondary": second["id"]}

    if intent == "use_item":
        item_part, target_part = split_connector(remainder)
        item = best_item(strip_fillers(item_part), context)
        if not item:
            intent = "interact"
            remainder = target_part if target_part else remainder
        else:
            target = best_target(strip_fillers(target_part), context) if target_part else None
            if not target:
                return {"intent": "select_item", "item": item["id"]}
            return {"intent": "use_item", "item": item["id"],
                    "target": target["id"], "target_kind": target["kind"]}

    if intent == "move":
        phrase = strip_fillers(remainder)
        direction = direction_in(phrase)
        if direction:
            return {"intent": "move_direction", "direction": direction}
        target = best_target(phrase, context)
        if not target:
            return {"intent": "unknown", "reason": "kein_ziel", "phrase": phrase}
        return {"intent": "move", "target": target["id"], "target_kind": target["kind"],
                "confidence": round(target["score"], 3)}

    if intent == "interact":
        phrase = strip_fillers(remainder)
        ordinal = ordinal_in(phrase)
        if ordinal > 0 and len(phrase) <= 12:
            hotspots = context.get("hotspots", [])
            if 1 <= ordinal <= len(hotspots):
                return {"intent": "interact", "target": hotspots[ordinal - 1]["id"], "target_kind": "hotspot"}
        target = best_target(phrase, context)
        if not target:
            return {"intent": "unknown", "reason": "kein_ziel", "phrase": phrase}
        return {"intent": "interact", "target": target["id"], "target_kind": target["kind"],
                "confidence": round(target["score"], 3)}

    if intent == "choose":
        return resolve_choice(remainder, context)

    if intent == "unknown":
        options = context.get("options", [])
        phrase = strip_fillers(normalized)
        if options:
            choice = resolve_choice(phrase, context)
            if choice["intent"] == "choose":
                return choice
        direction = direction_in(phrase)
        if direction:
            return {"intent": "move_direction", "direction": direction}
        target = best_target(phrase, context)
        if target and target["score"] >= STRONG:
            return {"intent": "interact", "target": target["id"], "target_kind": target["kind"]}
        return {"intent": "unknown", "phrase": phrase}

    return {"intent": intent}


def resolve_choice(remainder: str, context: dict) -> dict:
    options = context.get("options", [])
    phrase = strip_fillers(remainder)
    ordinal = ordinal_in(phrase)
    if 0 < ordinal <= len(options):
        return {"intent": "choose", "target": options[ordinal - 1]["id"]}
    best, best_score = None, 0.0
    for option in options:
        score = similarity(phrase, option.get("label", ""))
        if score > best_score:
            best_score, best = score, option
    if best and best_score >= ACCEPT:
        return {"intent": "choose", "target": best["id"], "confidence": round(best_score, 3)}
    return {"intent": "unknown", "reason": "keine_option"}


# ------------------------------------------------------------------ Probelauf

def build_context(project: Path) -> dict:
    story = json.loads((project / "data" / "prologue.json").read_text(encoding="utf-8"))
    room = story["locations"]["krankenstation"]
    return {
        # Im Spiel ist immer nur eine der beiden Terminalfassungen sichtbar;
        # die Nachbildung filtert genauso, sonst prueft sie einen Zustand,
        # den es nie gibt.
        "hotspots": [{"id": h["id"], "label": h.get("label", ""), "verb": h.get("verb", "")}
                     for h in room.get("hotspots", []) if h["id"] != "mira_terminal_after"],
        "exits": [{"id": e["id"], "label": e.get("label", ""), "verb": e.get("verb", "")}
                  for e in room.get("exits", [])],
        "items": [
            {"id": "film_conductive", "name": "Leitfähige Folie"},
            {"id": "swab_sterile", "name": "Steriler Tupfer"},
            {"id": "badge_cracked", "name": "Gesprungener Ausweis"},
        ],
        "options": [],
    }


CASES = [
    ("bewege dich zum Medizinschrank", "move", "medical_cabinet"),
    ("Bewege dich zur Behandlungsliege.", "move", "treatment_bed"),
    ("geh zum Terminal", "move", "mira_terminal"),
    ("geh in den Diagnosekorridor", "move", "to_diagnostics"),
    ("öffne den Medizinschrank", "interact", "medical_cabinet"),
    ("Öffne die Tür ohne Klinke", "interact", "sealed_door"),
    ("oeffne den schrank", "interact", "medical_cabinet"),
    ("untersuche das flackernde Terminal", "interact", "mira_terminal"),
    ("durchsuche die Behandlungsliege", "interact", "treatment_bed"),
    ("sieh dir den Diagnosespiegel an", "interact", "memory_mirror"),
    ("nimm den Ausweis", None, None),
    ("nach links", "move_direction", None),
    ("geh nach rechts", "move_direction", None),
    ("inventar", "inventory", None),
    ("zeige objekte", "hints", None),
    ("sieh dich um", "look_around", None),
    ("sei still", "stop_voice", None),
    ("wiederhole", "repeat", None),
    ("speichern", "save", None),
    ("journal", "journal", None),
    ("status", "status", None),
    ("was kann ich sagen", "help", None),
    ("benutze die Folie am Terminal", "use_item", "mira_terminal"),
    ("kombiniere die Folie mit dem Tupfer", "combine", None),
    ("Medizinschrank", "interact", "medical_cabinet"),
    ("blafasel wurstbrot", "unknown", None),
]

CHOICE_CASES = [
    ("antwort zwei", "choose", "b"),
    ("wähle die erste", "choose", "a"),
    ("option drei", "choose", "c"),
    ("zwei", "choose", "b"),
]


def main() -> int:
    project = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    context = build_context(project)
    print("Hotspots:", [h["label"] for h in context["hotspots"]])
    print()
    failures = 0
    for utterance, expected_intent, expected_target in CASES:
        result = parse(utterance, context)
        ok = True
        if expected_intent and result["intent"] != expected_intent:
            ok = False
        if expected_target and result.get("target") != expected_target:
            ok = False
        failures += 0 if ok else 1
        mark = "  " if ok else "!!"
        print(f'{mark} "{utterance}"\n     -> {result}')

    choice_context = dict(context)
    choice_context["options"] = [
        {"id": "a", "label": "Woher kennst du meinen Namen?"},
        {"id": "b", "label": "Sag mir, was du von mir brauchst."},
        {"id": "c", "label": "Verbindung trennen."},
    ]
    print()
    for utterance, expected_intent, expected_target in CHOICE_CASES:
        result = parse(utterance, choice_context)
        ok = result["intent"] == expected_intent and result.get("target") == expected_target
        failures += 0 if ok else 1
        print(f'{"  " if ok else "!!"} "{utterance}"\n     -> {result}')

    print(f"\n{failures} Abweichungen")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
