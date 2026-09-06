class_name NPSceneManager
extends RefCounted

var current_location_id := ""

func enter(location_id: String, state: Dictionary) -> void:
	current_location_id = location_id
	state["world"]["current_location"] = location_id
	var visited: Array = state.get("visited_locations", [])
	if not visited.has(location_id):
		visited.append(location_id)
	state["visited_locations"] = visited

