class_name PuzzleManager
extends RefCounted

var solved: Array[String] = []

func reset() -> void:
	solved.clear()

func restore(saved: Array) -> void:
	solved.clear()
	for puzzle_id in saved:
		var clean_id := str(puzzle_id)
		if not solved.has(clean_id):
			solved.append(clean_id)

func solve(puzzle_id: String) -> bool:
	if puzzle_id.is_empty() or solved.has(puzzle_id):
		return false
	solved.append(puzzle_id)
	return true

func is_solved(puzzle_id: String) -> bool:
	return solved.has(puzzle_id)

