class_name CharacterState
extends RefCounted

static func create(profile: Dictionary) -> Dictionary:
	var presentation := str(profile.get("presentation", "weiblich"))
	var default_name := "Mira Vale" if presentation == "weiblich" else "Marek Vale"
	return {
		"name": str(profile.get("name", default_name)).strip_edges(),
		"presentation": presentation,
		"subject_pronoun": "sie" if presentation == "weiblich" else "er",
		"object_pronoun": "ihr" if presentation == "weiblich" else "ihm",
		"logic": int(profile.get("logic", 1)),
		"empathy": int(profile.get("empathy", 1)),
		"instinct": int(profile.get("instinct", 1))
	}

