class_name ConsequenceSystem
extends RefCounted

static func apply(effects: Dictionary, state: Dictionary, inventory: InventoryManager, puzzles: PuzzleManager) -> Array[String]:
	var feedback: Array[String] = []
	var flags: Array = state.get("flags", [])
	for flag in effects.get("add_flags", []):
		var flag_id := str(flag)
		if not flags.has(flag_id):
			flags.append(flag_id)
	for flag in effects.get("remove_flags", []):
		flags.erase(str(flag))
	state["flags"] = flags
	for item_id in effects.get("add_items", []):
		var clean_id := str(item_id)
		if inventory.add_item(clean_id):
			feedback.append("ERHALTEN: " + str(inventory.get_item(clean_id).get("name", clean_id)))
	for item_id in effects.get("remove_items", []):
		inventory.remove_item(str(item_id))
	for puzzle_id in effects.get("solve_puzzles", []):
		puzzles.solve(str(puzzle_id))
	var world: Dictionary = state.get("world", {})
	for key in effects.get("world_delta", {}):
		world[key] = float(world.get(key, 0)) + float(effects["world_delta"][key])
	for key in effects.get("set_world", {}):
		world[key] = effects["set_world"][key]
	if effects.has("time_cost"):
		world["time_remaining"] = maxf(0.0, float(world.get("time_remaining", 72.0)) - float(effects["time_cost"]))
	state["world"] = world
	var relationships: Dictionary = state.get("relationships", {})
	for key in effects.get("relation_delta", {}):
		relationships[key] = int(relationships.get(key, 0)) + int(effects["relation_delta"][key])
	state["relationships"] = relationships
	var secrets: Array = state.get("secrets", [])
	for secret in effects.get("add_secrets", []):
		var secret_id := str(secret)
		if not secrets.has(secret_id):
			secrets.append(secret_id)
	state["secrets"] = secrets
	var journal: Array = state.get("journal", [])
	for entry in effects.get("add_journal", []):
		var entry_id := str(entry.get("id", "entry_%d" % journal.size()))
		var exists := false
		for old_entry in journal:
			if str(old_entry.get("id", "")) == entry_id:
				exists = true
				break
		if not exists:
			journal.append(entry.duplicate(true))
			feedback.append("JOURNAL AKTUALISIERT: " + str(entry.get("title", "Neuer Hinweis")))
	state["journal"] = journal
	if effects.has("ending"):
		state["ending"] = str(effects["ending"])
	return feedback

