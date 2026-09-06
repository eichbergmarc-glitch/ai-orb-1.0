class_name StoryManager
extends RefCounted

var story_data: Dictionary = {}
var locations: Dictionary = {}
var endings: Dictionary = {}

func load_data(path := "res://data/prologue.json") -> bool:
	if not FileAccess.file_exists(path):
		push_error("Storydatei fehlt: " + path)
		return false
	var file := FileAccess.open(path, FileAccess.READ)
	var parsed = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		push_error("Ungültige Storydatei: " + path)
		return false
	story_data = parsed
	locations = story_data.get("locations", {})
	endings = story_data.get("endings", {})
	return not locations.is_empty()

func get_location(location_id: String) -> Dictionary:
	return locations.get(location_id, {})

func get_hotspot(location_id: String, hotspot_id: String) -> Dictionary:
	for hotspot in get_location(location_id).get("hotspots", []):
		if str(hotspot.get("id", "")) == hotspot_id:
			return hotspot
	return {}

func get_exit(location_id: String, exit_id: String) -> Dictionary:
	for exit_data in get_location(location_id).get("exits", []):
		if str(exit_data.get("id", "")) == exit_id:
			return exit_data
	return {}

func get_ending(ending_id: String) -> Dictionary:
	return endings.get(ending_id, {})

