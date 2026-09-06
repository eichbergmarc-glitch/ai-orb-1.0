extends Node

const SPATIAL_PATH := "res://data/spatial_layouts.json"
const STORY_PATH := "res://data/prologue.json"
const FEMALE_TEXTURE := "res://assets/characters/protagonist_female.png"
const MALE_TEXTURE := "res://assets/characters/protagonist_male.png"
const JUNA_TEXTURE := "res://assets/characters/juna_falk.png"

var failures: Array[String] = []
var completed := false
var hotspot_counts: Dictionary = {}
var exit_counts: Dictionary = {}


func _ready() -> void:
	await get_tree().process_frame
	var spatial := _load_json(SPATIAL_PATH, "Raumlayout")
	var story := _load_json(STORY_PATH, "Prolog")
	_validate_assets_and_layout(spatial, story)
	if not spatial.is_empty() and not story.is_empty():
		_run_stage_behaviour(story)
	if not completed:
		failures.append("Der Bewegungstest wurde vorzeitig abgebrochen. Siehe die Fehlerausgabe darueber.")
	_finish()


func _run_stage_behaviour(story: Dictionary) -> void:
	var locations: Dictionary = story.get("locations", {})
	var chamber: Dictionary = locations.get("krankenstation", {})
	_expect(not chamber.is_empty(), "Die Aufwachkammer fehlt; Bewegungstest kann nicht ausgeführt werden.")
	if chamber.is_empty():
		return

	var stage := PointClickStage.new()
	stage.name = "PointClickStageUnderTest"
	stage.size = Vector2(1920.0, 1080.0)
	add_child(stage)
	stage.set_process(false)
	stage.hotspot_reached.connect(_on_hotspot_reached)
	stage.exit_reached.connect(_on_exit_reached)
	# Ohne Atem- und Blickbewegung ist die Kamerapositionierung reproduzierbar.
	stage.set_reduce_motion(true)
	stage.configure(chamber, chamber.get("hotspots", []), chamber.get("exits", []), [], "weiblich")

	# A hotspot is only executed after the character reaches its approach point.
	_expect(stage.queue_hotspot("treatment_bed"), "Hotspot treatment_bed konnte nicht als Laufziel gesetzt werden.")
	_expect(_count_for(hotspot_counts, "treatment_bed") == 0, "Hotspot-Aktion feuerte bereits beim Anklicken statt nach der Ankunft.")
	stage._process(1.0 / 120.0)
	_expect(_count_for(hotspot_counts, "treatment_bed") == 0, "Hotspot-Aktion feuerte vor Erreichen des Annäherungspunktes.")
	_advance(stage, 900)
	_expect(_count_for(hotspot_counts, "treatment_bed") == 1, "Hotspot-Aktion wurde nach der Ankunft nicht genau einmal ausgelöst.")
	_advance(stage, 180)
	_expect(_count_for(hotspot_counts, "treatment_bed") == 1, "Hotspot-Aktion wurde nach der Ankunft mehrfach ausgelöst.")

	# A genuine floor click must replace and cancel an outstanding hotspot intent.
	# The point below is deliberately outside every hitbox of this room, and it is
	# converted through the stage's own camera transform so the test stays valid
	# no matter how the view is framed.
	var hotspot_total_before_cancel := _total_count(hotspot_counts)
	_expect(stage.queue_hotspot("medical_cabinet"), "Hotspot medical_cabinet konnte nicht als Laufziel gesetzt werden.")
	# Nah genug an der Figur, damit der Punkt bei jeder Kamerastellung sichtbar
	# ist, und tief genug, um unter allen Hitboxen dieses Raums zu liegen.
	var floor_design := Vector2(stage.get_player_position().x - 220.0, 820.0)
	var floor_click := InputEventMouseButton.new()
	floor_click.button_index = MOUSE_BUTTON_LEFT
	floor_click.pressed = true
	floor_click.position = stage.design_to_local(floor_design)
	_expect(
		Rect2(Vector2.ZERO, stage.size).has_point(floor_click.position),
		"Der Bodenpunkt liegt ausserhalb des sichtbaren Ausschnitts; der Test kann nicht klicken."
	)
	stage._gui_input(floor_click)
	_advance(stage, 900)
	_expect(_total_count(hotspot_counts) == hotspot_total_before_cancel, "Ein Bodenklick hat den ausstehenden Hotspot-Intent nicht storniert.")
	_expect(_count_for(hotspot_counts, "medical_cabinet") == 0, "Der stornierte Hotspot medical_cabinet wurde trotzdem ausgelöst.")
	_expect(
		stage.get_player_position().distance_to(Vector2(1090.0, 735.0)) > 60.0,
		"Der Bodenklick hat die Figur trotzdem zum Medizinschrank laufen lassen."
	)
	# Die Ego-Kamera ist ein Ausschnitt: Weltpunkt und Bildpunkt muessen sich
	# verlustfrei ineinander umrechnen lassen, sonst zielt jeder Klick daneben.
	for probe in [Vector2(300.0, 780.0), Vector2(960.0, 540.0), Vector2(1500.0, 820.0)]:
		var back := stage.local_to_design(stage.design_to_local(probe))
		_expect(
			back.distance_to(probe) < 0.5,
			"Kameraumrechnung verliert Genauigkeit bei %s (zurueck: %s)." % [probe, back]
		)
	_expect(
		stage.get_player_position().distance_to(floor_design) < 90.0,
		"Der Bodenklick hat die Figur nicht zum angeklickten Punkt bewegt."
	)

	# Exits use the same approach contract and fire only after walking there.
	_expect(stage.queue_exit("to_diagnostics"), "Exit to_diagnostics konnte nicht als Laufziel gesetzt werden.")
	_expect(_count_for(exit_counts, "to_diagnostics") == 0, "Exit feuerte bereits beim Anklicken statt nach der Ankunft.")
	stage._process(1.0 / 120.0)
	_expect(_count_for(exit_counts, "to_diagnostics") == 0, "Exit feuerte vor Erreichen des Annäherungspunktes.")
	_advance(stage, 1200)
	_expect(_count_for(exit_counts, "to_diagnostics") == 1, "Exit wurde nach der Annäherung nicht genau einmal ausgelöst.")
	_advance(stage, 180)
	_expect(_count_for(exit_counts, "to_diagnostics") == 1, "Exit wurde nach der Ankunft mehrfach ausgelöst.")

	completed = true
	stage.queue_free()


func _validate_assets_and_layout(spatial: Dictionary, story: Dictionary) -> void:
	_expect(_resource_exists(FEMALE_TEXTURE), "Weibliche Charaktertextur fehlt: " + FEMALE_TEXTURE)
	_expect(_resource_exists(MALE_TEXTURE), "Männliche Charaktertextur fehlt: " + MALE_TEXTURE)
	_expect(_resource_exists(JUNA_TEXTURE), "Juna-Charaktertextur fehlt: " + JUNA_TEXTURE)
	if spatial.is_empty() or story.is_empty():
		return

	var canvas: Variant = spatial.get("canvas", [])
	_expect(canvas is Array and canvas.size() >= 2 and int(canvas[0]) == 1920 and int(canvas[1]) == 1080, "Raumlayout verwendet nicht die erwarteten 1920x1080-Designkoordinaten.")
	var spatial_locations: Dictionary = spatial.get("locations", {})
	var story_locations: Dictionary = story.get("locations", {})
	_expect(story_locations.size() == 7, "Der Prolog enthält nicht die erwarteten sieben Story-Orte.")

	for location_id_value in story_locations:
		var location_id := str(location_id_value)
		_expect(spatial_locations.has(location_id), "Raumlayout fehlt für Story-Ort: " + location_id)
		if not spatial_locations.has(location_id):
			continue
		var story_location: Dictionary = story_locations[location_id]
		var spatial_location: Dictionary = spatial_locations[location_id]
		var background_path := str(spatial_location.get("background", ""))
		_expect(not background_path.is_empty(), "%s: Backgroundpfad fehlt im Raumlayout." % location_id)
		_expect(_resource_exists(background_path), "%s: Backgrounddatei fehlt: %s" % [location_id, background_path])
		for actor_value in spatial_location.get("actors", []):
			if actor_value is Dictionary:
				var actor_texture := str(actor_value.get("texture", ""))
				_expect(_resource_exists(actor_texture), "%s: NPC-Textur fehlt: %s" % [location_id, actor_texture])

		var walk: Variant = spatial_location.get("walk", [])
		_expect(walk is Array and walk.size() >= 3, "%s: begehbares Polygon besitzt weniger als drei Punkte." % location_id)
		var spatial_spots: Dictionary = spatial_location.get("spots", {})
		for hotspot_value in story_location.get("hotspots", []):
			if not hotspot_value is Dictionary:
				continue
			var hotspot_id := str(hotspot_value.get("id", ""))
			_expect(spatial_spots.has(hotspot_id), "%s: räumliche Daten fehlen für Hotspot %s." % [location_id, hotspot_id])
			if spatial_spots.has(hotspot_id):
				_validate_interactive_shape(location_id, "Hotspot", hotspot_id, spatial_spots[hotspot_id])

		var spatial_exits: Dictionary = spatial_location.get("exits", {})
		for exit_value in story_location.get("exits", []):
			if not exit_value is Dictionary:
				continue
			var exit_id := str(exit_value.get("id", ""))
			_expect(spatial_exits.has(exit_id), "%s: räumliche Daten fehlen für Exit %s." % [location_id, exit_id])
			if spatial_exits.has(exit_id):
				_validate_interactive_shape(location_id, "Exit", exit_id, spatial_exits[exit_id])

	# Detect orphaned spatial layouts as well as missing ones.
	for location_id_value in spatial_locations:
		var location_id := str(location_id_value)
		_expect(story_locations.has(location_id), "Raumlayout verweist auf unbekannten Story-Ort: " + location_id)


func _validate_interactive_shape(location_id: String, kind: String, interaction_id: String, data: Variant) -> void:
	_expect(data is Dictionary, "%s/%s %s: räumlicher Eintrag ist kein Objekt." % [location_id, kind, interaction_id])
	if not data is Dictionary:
		return
	var hitbox: Variant = data.get("r", [])
	var approach: Variant = data.get("a", [])
	_expect(hitbox is Array and hitbox.size() >= 4, "%s/%s %s: Hitbox r ist unvollständig." % [location_id, kind, interaction_id])
	_expect(approach is Array and approach.size() >= 2, "%s/%s %s: Annäherungspunkt a fehlt." % [location_id, kind, interaction_id])


func _advance(stage: PointClickStage, maximum_steps: int) -> void:
	for step in range(maximum_steps):
		stage._process(1.0 / 120.0)


func _on_hotspot_reached(hotspot_id: String) -> void:
	hotspot_counts[hotspot_id] = _count_for(hotspot_counts, hotspot_id) + 1


func _on_exit_reached(exit_id: String) -> void:
	exit_counts[exit_id] = _count_for(exit_counts, exit_id) + 1


func _count_for(counts: Dictionary, key: String) -> int:
	return int(counts.get(key, 0))


func _total_count(counts: Dictionary) -> int:
	var total := 0
	for value in counts.values():
		total += int(value)
	return total


func _resource_exists(path: String) -> bool:
	return not path.is_empty() and (ResourceLoader.exists(path) or FileAccess.file_exists(path))


func _load_json(path: String, label: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		failures.append("%sdatei fehlt: %s" % [label + "-", path])
		return {}
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		failures.append("%sdatei konnte nicht geöffnet werden: %s" % [label + "-", path])
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		failures.append("%sdatei enthält kein gültiges JSON-Objekt: %s" % [label + "-", path])
		return {}
	return parsed


func _expect(condition: bool, message: String) -> void:
	if not condition:
		failures.append(message)


func _finish() -> void:
	if failures.is_empty():
		print("NULLPROTOKOLL – Point-and-Click-Test bestanden")
		print("  Annäherung, einmalige Hotspot-/Exit-Auslösung und Intent-Abbruch geprüft")
		print("  3 Charaktertexturen, 7 Hintergründe und vollständige räumliche Storyabdeckung geprüft")
		get_tree().quit(0)
		return
	printerr("Point-and-Click-Test fehlgeschlagen (%d):" % failures.size())
	for failure in failures:
		printerr("- " + failure)
	get_tree().quit(1)
