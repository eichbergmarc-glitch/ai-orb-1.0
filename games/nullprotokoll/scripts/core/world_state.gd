class_name WorldState
extends RefCounted

static func create() -> Dictionary:
	return {
		"global_threat": 12,
		"ai_attention": 4,
		"humanity": 50,
		"moral_burden": 0,
		"memory_fragments": 0,
		"time_remaining": 72.0,
		"current_location": "krankenstation",
		"active_faction": "keine",
		"world_condition": "blackout"
	}

