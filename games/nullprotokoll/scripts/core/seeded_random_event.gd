class_name SeededRandomEvent
extends RefCounted

var rng := RandomNumberGenerator.new()

func begin(seed_value: int) -> void:
	rng.seed = seed_value

func restore(seed_value: int, saved_state: int) -> void:
	rng.seed = seed_value
	if saved_state > 0:
		rng.state = saved_state

func choose_weighted(events: Array) -> Dictionary:
	if events.is_empty():
		return {}
	var total := 0.0
	for event in events:
		total += maxf(0.0, float(event.get("weight", 1.0)))
	if total <= 0.0:
		return events[0]
	var roll := rng.randf_range(0.0, total)
	var cursor := 0.0
	for event in events:
		cursor += maxf(0.0, float(event.get("weight", 1.0)))
		if roll <= cursor:
			return event
	return events.back()

func current_state() -> int:
	return rng.state

