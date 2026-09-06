extends Node

## Prüft die Sprachschicht ohne Mikrofon:
##   * Der Befehlsparser gegen echte Objektbezeichnungen aus prologue.json.
##   * Den Schlüssel der Sprachzeilen, damit vorgerenderte Dateien gefunden werden.
##   * Vorhandensein der Klangdateien und der Zwischensequenzdaten.

const STORY_PATH := "res://data/prologue.json"
const CUTSCENE_PATH := "res://data/cutscenes.json"
const AMBIENCE_DIR := "res://assets/audio/ambience/"
const SFX_DIR := "res://assets/audio/sfx/"

const REQUIRED_AMBIENCE := [
	"krankenstation", "diagnostiklabor", "sicherheitsrotunde",
	"wartungsgalerie", "quarantaene", "kaltarchiv", "relaiskern"
]
const REQUIRED_SFX := [
	"item_pickup", "device_use", "comm_open", "door_move", "inspect",
	"ui_click", "ui_confirm", "voice_listen_start", "voice_listen_stop",
	"voice_fail", "event_sting"
]

var failures: Array[String] = []
var completed := false


func _ready() -> void:
	await get_tree().process_frame
	_run_checks()
	if not completed:
		failures.append("Der Sprachtest wurde vorzeitig abgebrochen. Siehe die Fehlerausgabe darueber.")
	_finish()


func _run_checks() -> void:
	var story := _load_json(STORY_PATH)
	_check_parser(story)
	_check_voice_keys()
	_check_assets()
	_check_cutscenes(story)
	completed = true


func _check_parser(story: Dictionary) -> void:
	var room: Dictionary = story.get("locations", {}).get("krankenstation", {})
	if room.is_empty():
		failures.append("Aufwachkammer fehlt; Sprachbefehle können nicht geprüft werden.")
		return

	var hotspots: Array = []
	for hotspot_value in room.get("hotspots", []):
		if not hotspot_value is Dictionary:
			continue
		var hotspot: Dictionary = hotspot_value
		# Von den beiden Terminalfassungen ist im Spiel immer nur eine sichtbar.
		if str(hotspot.get("id", "")) == "mira_terminal_after":
			continue
		hotspots.append({
			"id": str(hotspot.get("id", "")),
			"label": str(hotspot.get("label", "")),
			"verb": str(hotspot.get("verb", ""))
		})
	var exits: Array = []
	for exit_value in room.get("exits", []):
		if exit_value is Dictionary:
			exits.append({"id": str(exit_value.get("id", "")), "label": str(exit_value.get("label", ""))})

	var context := {
		"hotspots": hotspots,
		"exits": exits,
		"items": [
			{"id": "film_conductive", "name": "Leitfähige Folie"},
			{"id": "swab_sterile", "name": "Steriler Tupfer"}
		],
		"options": []
	}

	# Bewegen und Handeln sind bewusst getrennt: "geh zu" läuft nur hin,
	# "öffne" läuft hin und handelt danach.
	_expect_command("bewege dich zum Medizinschrank", context, "move", "medical_cabinet")
	_expect_command("Bewege dich zur Behandlungsliege.", context, "move", "treatment_bed")
	_expect_command("geh in den Diagnosekorridor", context, "move", "to_diagnostics")
	_expect_command("öffne den Medizinschrank", context, "interact", "medical_cabinet")
	_expect_command("Öffne die Tür ohne Klinke", context, "interact", "sealed_door")
	_expect_command("oeffne den schrank", context, "interact", "medical_cabinet")
	_expect_command("untersuche das flackernde Terminal", context, "interact", "mira_terminal")
	_expect_command("durchsuche die Behandlungsliege", context, "interact", "treatment_bed")
	_expect_command("sieh dir den Diagnosespiegel an", context, "interact", "memory_mirror")
	_expect_command("Medizinschrank", context, "interact", "medical_cabinet")
	_expect_command("benutze die Folie am Terminal", context, "use_item", "mira_terminal")

	_expect_intent("nach links", context, "move_direction")
	_expect_intent("geh nach rechts", context, "move_direction")
	_expect_intent("kombiniere die Folie mit dem Tupfer", context, "combine")
	_expect_intent("inventar", context, "inventory")
	_expect_intent("journal", context, "journal")
	_expect_intent("status", context, "status")
	_expect_intent("zeige objekte", context, "hints")
	_expect_intent("sieh dich um", context, "look_around")
	_expect_intent("sei still", context, "stop_voice")
	_expect_intent("wiederhole", context, "repeat")
	_expect_intent("speichern", context, "save")
	_expect_intent("was kann ich sagen", context, "help")
	_expect_intent("blafasel wurstbrot", context, "unknown")

	var choice_context := context.duplicate(true)
	choice_context["options"] = [
		{"id": "ask_name", "label": "Woher kennst du meinen Namen?"},
		{"id": "ask_need", "label": "Sag zuerst, was du von mir brauchst."},
		{"id": "mute", "label": "Verbindung trennen."}
	]
	_expect_command("antwort zwei", choice_context, "choose", "ask_need")
	_expect_command("wähle die erste", choice_context, "choose", "ask_name")
	_expect_command("option drei", choice_context, "choose", "mute")
	_expect_command("zwei", choice_context, "choose", "ask_need")

	var combination := NPCommandParser.parse("kombiniere die Folie mit dem Tupfer", context)
	_expect(str(combination.get("item", "")) == "film_conductive", "Kombination: erster Gegenstand falsch erkannt.")
	_expect(str(combination.get("secondary", "")) == "swab_sterile", "Kombination: zweiter Gegenstand falsch erkannt.")


func _check_voice_keys() -> void:
	# Der Schlüssel muss ausschließlich vom normalisierten Text abhängen,
	# sonst finden vorgerenderte Dateien ihre Zeile nicht wieder.
	var plain := NPVoiceManager.voice_key("Hallo Welt")
	_expect(plain.length() == 16, "Sprachschlüssel hat nicht die erwartete Länge.")
	_expect(NPVoiceManager.voice_key("  Hallo   Welt  ") == plain, "Sprachschlüssel ignoriert überflüssige Leerzeichen nicht.")
	_expect(NPVoiceManager.voice_key("Hallo\tWelt") == plain, "Sprachschlüssel behandelt Tabulatoren nicht wie Leerzeichen.")
	_expect(NPVoiceManager.voice_key("Hallo Welt!") != plain, "Sprachschlüssel unterscheidet unterschiedliche Texte nicht.")

	var manager := NPVoiceManager.new()
	manager.set_presentation("weiblich")
	_expect(manager.role_for_log_entry("MIRA", "dialogue") == "mira", "MIRA wird nicht der Systemstimme zugeordnet.")
	_expect(manager.role_for_log_entry("Dr. Juna Falk", "dialogue") == "juna", "Juna wird nicht ihrer Stimme zugeordnet.")
	_expect(manager.role_for_log_entry("Samir", "dialogue") == "samir", "Samir wird nicht seiner Stimme zugeordnet.")
	_expect(manager.role_for_log_entry("", "action") == "gedanke_w", "Erzähltext wird nicht als Gedanke gesprochen.")
	manager.set_presentation("maennlich")
	_expect(manager.role_for_log_entry("", "action") == "gedanke_m", "Männliche Spielfigur erhält nicht die männliche Gedankenstimme.")
	manager.free()


func _check_assets() -> void:
	for name in REQUIRED_AMBIENCE:
		_expect(_resource_exists(AMBIENCE_DIR + name + ".ogg"), "Raumatmosphäre fehlt: " + name)
	for name in REQUIRED_SFX:
		_expect(_resource_exists(SFX_DIR + name + ".ogg"), "Effektgeräusch fehlt: " + name)


func _check_cutscenes(story: Dictionary) -> void:
	var document := _load_json(CUTSCENE_PATH)
	var sequences: Dictionary = document.get("sequences", {})
	_expect(not sequences.is_empty(), "Es sind keine Zwischensequenzen definiert.")
	_expect(sequences.has("prolog_start"), "Die Eröffnungssequenz prolog_start fehlt.")

	for ending_id_value in story.get("endings", {}):
		var trigger := "ende_" + str(ending_id_value)
		_expect(sequences.has(trigger), "Zwischensequenz fehlt für Ende: " + str(ending_id_value))

	for trigger_value in sequences:
		var beats: Variant = sequences[trigger_value]
		_expect(beats is Array and not (beats as Array).is_empty(), "Sequenz ohne Inhalt: " + str(trigger_value))
		if not beats is Array:
			continue
		for beat_value in beats:
			if not beat_value is Dictionary:
				failures.append("Sequenz %s enthält einen ungültigen Eintrag." % str(trigger_value))
				continue
			var beat: Dictionary = beat_value
			_expect(not str(beat.get("text", "")).strip_edges().is_empty(), "Sequenz %s: Beat ohne Text." % str(trigger_value))
			var background := str(beat.get("background", ""))
			if not background.is_empty():
				_expect(
					_resource_exists("res://assets/backgrounds/%s.png" % background),
					"Sequenz %s verweist auf fehlenden Hintergrund: %s" % [str(trigger_value), background]
				)
			var character := str(beat.get("character", ""))
			if character == "juna":
				_expect(_resource_exists("res://assets/characters/juna_falk.png"), "Juna-Porträt fehlt für Zwischensequenz.")
			elif character == "protagonist":
				_expect(_resource_exists("res://assets/characters/protagonist_female.png"), "Weibliches Porträt fehlt für Zwischensequenz.")
				_expect(_resource_exists("res://assets/characters/protagonist_male.png"), "Männliches Porträt fehlt für Zwischensequenz.")


func _expect_command(utterance: String, context: Dictionary, expected_intent: String, expected_target: String) -> void:
	var result := NPCommandParser.parse(utterance, context)
	var intent := str(result.get("intent", ""))
	var target := str(result.get("target", ""))
	_expect(
		intent == expected_intent and target == expected_target,
		"„%s“ ergab %s/%s statt %s/%s." % [utterance, intent, target, expected_intent, expected_target]
	)


func _expect_intent(utterance: String, context: Dictionary, expected_intent: String) -> void:
	var result := NPCommandParser.parse(utterance, context)
	var intent := str(result.get("intent", ""))
	_expect(intent == expected_intent, "„%s“ ergab %s statt %s." % [utterance, intent, expected_intent])


func _resource_exists(path: String) -> bool:
	return not path.is_empty() and (ResourceLoader.exists(path) or FileAccess.file_exists(path))


func _load_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		failures.append("Datei fehlt: " + path)
		return {}
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		failures.append("Datei nicht lesbar: " + path)
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		failures.append("Kein gültiges JSON-Objekt: " + path)
		return {}
	return parsed


func _expect(condition: bool, message: String) -> void:
	if not condition:
		failures.append(message)


func _finish() -> void:
	if failures.is_empty():
		print("NULLPROTOKOLL – Sprachtest bestanden")
		print("  28 gesprochene Befehle gegen echte Objektbezeichnungen geprüft")
		print("  Sprachschlüssel, Rollenzuordnung, 18 Klangdateien und Zwischensequenzen geprüft")
		get_tree().quit(0)
		return
	printerr("Sprachtest fehlgeschlagen (%d):" % failures.size())
	for failure in failures:
		printerr("- " + failure)
	get_tree().quit(1)
