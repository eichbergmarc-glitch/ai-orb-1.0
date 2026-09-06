class_name InventoryManager
extends RefCounted

var item_definitions: Dictionary = {}
var recipes: Array = []
var inventory: Array[String] = []
var selected_item_id := ""

func load_data(items_path := "res://data/items.json", recipes_path := "res://data/recipes.json") -> bool:
	item_definitions = _load_json(items_path)
	var recipe_data = _load_json(recipes_path)
	recipes = recipe_data.get("recipes", []) if recipe_data is Dictionary else []
	return not item_definitions.is_empty() and not recipes.is_empty()

func reset() -> void:
	inventory.clear()
	selected_item_id = ""

func restore(saved_items: Array) -> void:
	inventory.clear()
	for item_id in saved_items:
		if item_definitions.has(str(item_id)):
			inventory.append(str(item_id))
	selected_item_id = ""

func add_item(item_id: String) -> bool:
	if not item_definitions.has(item_id) or inventory.has(item_id):
		return false
	inventory.append(item_id)
	return true

func remove_item(item_id: String) -> bool:
	var index := inventory.find(item_id)
	if index < 0:
		return false
	inventory.remove_at(index)
	if selected_item_id == item_id:
		selected_item_id = ""
	return true

func has_item(item_id: String) -> bool:
	return inventory.has(item_id)

func get_item(item_id: String) -> Dictionary:
	return item_definitions.get(item_id, {})

func get_all_items() -> Array:
	var result: Array = []
	for item_id in inventory:
		var definition: Dictionary = get_item(item_id).duplicate(true)
		definition["id"] = item_id
		result.append(definition)
	return result

func combine(first_id: String, second_id: String) -> Dictionary:
	if first_id == second_id:
		return {"success": false, "text": "Mit sich selbst ergibt der Gegenstand nichts Neues."}
	if not has_item(first_id) or not has_item(second_id):
		return {"success": false, "text": "Mindestens eines der Teile ist nicht mehr im Inventar."}
	var candidate := [first_id, second_id]
	candidate.sort()
	for recipe_data in recipes:
		var inputs: Array = recipe_data.get("inputs", []).duplicate()
		inputs.sort()
		if inputs == candidate:
			remove_item(first_id)
			remove_item(second_id)
			var result_id := str(recipe_data.get("result", ""))
			add_item(result_id)
			return {
				"success": true,
				"result": result_id,
				"puzzle_id": str(recipe_data.get("puzzle_id", "")),
				"text": str(recipe_data.get("success_text", "Die Teile greifen ineinander."))
			}
	var first_name := str(get_item(first_id).get("name", first_id))
	var second_name := str(get_item(second_id).get("name", second_id))
	return {"success": false, "text": "%s und %s passen in dieser Form nicht zusammen." % [first_name, second_name]}

func _load_json(path: String):
	if not FileAccess.file_exists(path):
		push_error("Datendatei fehlt: " + path)
		return {}
	var file := FileAccess.open(path, FileAccess.READ)
	var parsed = JSON.parse_string(file.get_as_text())
	if parsed == null:
		push_error("Ungültiges JSON: " + path)
		return {}
	return parsed

