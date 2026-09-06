class_name EventCondition
extends RefCounted

static func evaluate(conditions: Dictionary, state: Dictionary, inventory: InventoryManager, puzzles: PuzzleManager) -> bool:
	if conditions.is_empty():
		return true
	var flags: Array = state.get("flags", [])
	for flag in conditions.get("flags_all", []):
		if not flags.has(str(flag)):
			return false
	for flag in conditions.get("flags_none", []):
		if flags.has(str(flag)):
			return false
	for item_id in conditions.get("items_all", []):
		if not inventory.has_item(str(item_id)):
			return false
	for item_id in conditions.get("items_none", []):
		if inventory.has_item(str(item_id)):
			return false
	for puzzle_id in conditions.get("puzzles_all", []):
		if not puzzles.is_solved(str(puzzle_id)):
			return false
	var player: Dictionary = state.get("player", {})
	for key in conditions.get("stats_min", {}):
		if int(player.get(key, 0)) < int(conditions["stats_min"][key]):
			return false
	var relationships: Dictionary = state.get("relationships", {})
	for key in conditions.get("relations_min", {}):
		if int(relationships.get(key, 0)) < int(conditions["relations_min"][key]):
			return false
	var world: Dictionary = state.get("world", {})
	for key in conditions.get("world_min", {}):
		if float(world.get(key, 0)) < float(conditions["world_min"][key]):
			return false
	for key in conditions.get("world_max", {}):
		if float(world.get(key, 0)) > float(conditions["world_max"][key]):
			return false
	for key in conditions.get("world_equals", {}):
		if world.get(key) != conditions["world_equals"][key]:
			return false
	for interaction_id in conditions.get("interactions_all", []):
		if not state.get("completed_interactions", []).has(str(interaction_id)):
			return false
	return true

