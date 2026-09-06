class_name DialogueManager
extends RefCounted

var dialogues: Dictionary = {}
var active_dialogue_id := ""
var active_node_id := ""

func load_data(path := "res://data/dialogues.json") -> bool:
	if not FileAccess.file_exists(path):
		push_error("Dialogdatei fehlt: " + path)
		return false
	var file := FileAccess.open(path, FileAccess.READ)
	var parsed = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		push_error("Ungültige Dialogdatei: " + path)
		return false
	dialogues = parsed
	return not dialogues.is_empty()

func start(dialogue_id: String) -> Dictionary:
	var dialogue: Dictionary = dialogues.get(dialogue_id, {})
	if dialogue.is_empty():
		return {}
	active_dialogue_id = dialogue_id
	active_node_id = str(dialogue.get("start", "start"))
	return current_node()

func current_node() -> Dictionary:
	if active_dialogue_id.is_empty() or active_node_id.is_empty():
		return {}
	return dialogues.get(active_dialogue_id, {}).get("nodes", {}).get(active_node_id, {})

func choose(option_id: String) -> Dictionary:
	var node := current_node()
	for option in node.get("options", []):
		if str(option.get("id", "")) != option_id:
			continue
		var next_id := str(option.get("next", ""))
		if bool(option.get("end", false)) or next_id.is_empty():
			active_dialogue_id = ""
			active_node_id = ""
		else:
			active_node_id = next_id
		return option
	return {}

func is_active() -> bool:
	return not active_dialogue_id.is_empty()

func stop() -> void:
	active_dialogue_id = ""
	active_node_id = ""

