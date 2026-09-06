extends Node

signal state_changed
signal save_completed(success: bool)

const SAVE_VERSION := 1

var story := StoryManager.new()
var dialogue := DialogueManager.new()
var inventory := InventoryManager.new()
var puzzles := PuzzleManager.new()
var scene_manager := NPSceneManager.new()
var random_events := SeededRandomEvent.new()
var save_manager := NPSaveManager.new()
var audio_manager := NPAudioManager.new()
var voice := NPVoiceManager.new()
var speech := NPSpeechInput.new()

var state: Dictionary = {}
var settings: Dictionary = {}
var data_ready := false

func _ready() -> void:
	data_ready = story.load_data() and dialogue.load_data() and inventory.load_data()
	settings = _default_settings()
	settings.merge(save_manager.load_settings(), true)
	# Ton, Sprachausgabe und Mikrofon brauchen einen Platz im Szenenbaum.
	audio_manager.name = "AudioManager"
	voice.name = "VoiceManager"
	speech.name = "SpeechInput"
	add_child(audio_manager)
	add_child(voice)
	add_child(speech)
	_apply_audio_settings()

func _default_settings() -> Dictionary:
	return {
		"text_scale": 1.0,
		"master_volume": 0.8,
		"music_volume": 0.55,
		"effects_volume": 0.75,
		"high_contrast": false,
		"reduce_motion": false,
		"show_hotspot_labels": true,
		"auto_scroll": true,
		"fullscreen": false,
		"voice_volume": 0.9,
		"voice_enabled": true,
		"voice_thoughts": true,
		"voice_system_fallback": false,
		"speech_enabled": true,
		"speech_hands_free": false
	}

func _apply_audio_settings() -> void:
	audio_manager.apply_settings(settings)
	voice.apply_settings(settings)
	voice.set_presentation(str(state.get("player", {}).get("presentation", "weiblich")))
	speech.set_enabled(bool(settings.get("speech_enabled", true)))
	speech.set_hands_free(bool(settings.get("speech_hands_free", false)))

func new_game(profile: Dictionary, requested_seed := 0) -> bool:
	if not data_ready:
		return false
	inventory.reset()
	puzzles.reset()
	dialogue.stop()
	var seed_value := int(requested_seed)
	if seed_value == 0:
		seed_value = int(Time.get_unix_time_from_system() * 1000.0) ^ randi()
	random_events.begin(seed_value)
	state = {
		"save_version": SAVE_VERSION,
		"player": CharacterState.create(profile),
		"world": WorldState.create(),
		"flags": [],
		"relationships": {"mira": 0, "juna": 0, "samir": 0},
		"visited_locations": [],
		"completed_interactions": [],
		"triggered_events": [],
		"journal": [{
			"id": "ziel_erwachen",
			"category": "Ziele",
			"title": "Die Kammer verlassen",
			"text": "Finde heraus, warum ASTER-4 im Notbetrieb läuft und weshalb dein Name im System hinterlegt ist.",
			"status": "Aktiv"
		}],
		"secrets": [],
		"log": [],
		"ending": "",
		"seed": seed_value,
		"rng_state": random_events.current_state()
	}
	_add_log("system", "PROLOG // DAS ERWACHEN", "heading")
	_add_log("system", "EUROPAWEITER NETZAUSFALL · ASTER-4 · 03:17", "system")
	enter_location("krankenstation", false)
	save_game()
	state_changed.emit()
	return true

func has_active_game() -> bool:
	return not state.is_empty()

func get_current_location() -> Dictionary:
	return story.get_location(str(state.get("world", {}).get("current_location", "")))

func get_visible_hotspots() -> Array:
	var result: Array = []
	for hotspot in get_current_location().get("hotspots", []):
		if EventCondition.evaluate(hotspot.get("visible_conditions", {}), state, inventory, puzzles):
			result.append(hotspot)
	return result

func get_exits() -> Array:
	return get_current_location().get("exits", [])

func enter_location(location_id: String, autosave := true) -> Dictionary:
	var location := story.get_location(location_id)
	if location.is_empty():
		return {"success": false, "text": "Dieser Ort ist nicht definiert."}
	var first_visit: bool = not state.get("visited_locations", []).has(location_id)
	scene_manager.enter(location_id, state)
	audio_manager.play_ambience(location_id)
	_add_log(str(location.get("title", location_id)), format_text(str(location.get("description", ""))), "location")
	if first_visit:
		ConsequenceSystem.apply(location.get("entry_effects", {}), state, inventory, puzzles)
		_trigger_location_event(location)
	if autosave:
		save_game()
	if location_id == "relaiskern" and str(state.get("ending", "")).is_empty():
		save_checkpoint()
	state_changed.emit()
	return {"success": true, "location": location}

func travel(exit_id: String) -> Dictionary:
	var current_id := str(state.get("world", {}).get("current_location", ""))
	var exit_data := story.get_exit(current_id, exit_id)
	if exit_data.is_empty():
		return {"success": false, "text": "Dort gibt es keinen Weg."}
	if not EventCondition.evaluate(exit_data.get("conditions", {}), state, inventory, puzzles):
		var blocked := format_text(str(exit_data.get("blocked_text", "Der Weg ist noch versperrt.")))
		_add_log("", blocked, "action")
		state_changed.emit()
		return {"success": false, "text": blocked}
	var effects_feedback := ConsequenceSystem.apply(exit_data.get("effects", {}), state, inventory, puzzles)
	for line in effects_feedback:
		_add_log("system", line, "system")
	return enter_location(str(exit_data.get("to", "")))

func interact(hotspot_id: String) -> Dictionary:
	var location_id := str(state.get("world", {}).get("current_location", ""))
	var hotspot := story.get_hotspot(location_id, hotspot_id)
	if hotspot.is_empty():
		return {"success": false, "text": "Nichts reagiert."}
	if not inventory.selected_item_id.is_empty():
		return use_selected_item(hotspot_id)
	if not EventCondition.evaluate(hotspot.get("conditions", {}), state, inventory, puzzles):
		var locked_text := format_text(str(hotspot.get("locked_text", "Damit kommst du noch nicht weiter.")))
		_add_log("", locked_text, "action")
		state_changed.emit()
		return {"success": false, "text": locked_text}
	var key := location_id + ":" + hotspot_id
	var completed: Array = state.get("completed_interactions", [])
	if bool(hotspot.get("once", false)) and completed.has(key):
		var repeat_text := format_text(str(hotspot.get("repeat_text", "Hier gibt es nichts Neues mehr.")))
		_add_log("", repeat_text, "action")
		state_changed.emit()
		return {"success": true, "text": repeat_text}
	var text_value := format_text(str(hotspot.get("text", "")))
	if not text_value.is_empty():
		_add_log(str(hotspot.get("speaker", "")), text_value, str(hotspot.get("kind", "action")))
	if hotspot.has("dialogue"):
		var node := start_dialogue(str(hotspot["dialogue"]))
		return {"success": true, "dialogue": node}
	if hotspot.has("choices"):
		return {"success": true, "choices": _filter_options(hotspot["choices"]), "context": hotspot_id}
	_apply_and_complete(hotspot.get("effects", {}), key, bool(hotspot.get("once", false)))
	return {"success": true, "text": text_value}

func choose_interaction(hotspot_id: String, choice_id: String) -> Dictionary:
	var location_id := str(state.get("world", {}).get("current_location", ""))
	var hotspot := story.get_hotspot(location_id, hotspot_id)
	for choice in hotspot.get("choices", []):
		if str(choice.get("id", "")) != choice_id:
			continue
		if not EventCondition.evaluate(choice.get("conditions", {}), state, inventory, puzzles):
			return {"success": false, "text": "Diese Möglichkeit steht dir nicht offen."}
		var choice_text := format_text(str(choice.get("text", "")))
		_add_log(str(choice.get("speaker", "")), choice_text, str(choice.get("kind", "choice")))
		_apply_and_complete(choice.get("effects", {}), location_id + ":" + hotspot_id, bool(hotspot.get("once", false)))
		if state.get("ending", "") != "":
			return {"success": true, "ending": state["ending"]}
		return {"success": true, "text": choice_text}
	return {"success": false, "text": "Die Entscheidung ist nicht definiert."}

func use_selected_item(hotspot_id: String) -> Dictionary:
	var item_id := inventory.selected_item_id
	var location_id := str(state.get("world", {}).get("current_location", ""))
	var hotspot := story.get_hotspot(location_id, hotspot_id)
	var uses: Dictionary = hotspot.get("item_uses", {})
	if not uses.has(item_id):
		var item_name := str(inventory.get_item(item_id).get("name", item_id))
		var fail_text := "%s hilft dir bei %s nicht weiter." % [item_name, str(hotspot.get("label", "diesem Objekt"))]
		_add_log("", fail_text, "action")
		state_changed.emit()
		return {"success": false, "text": fail_text}
	var use_data: Dictionary = uses[item_id]
	if not EventCondition.evaluate(use_data.get("conditions", {}), state, inventory, puzzles):
		var blocked := format_text(str(use_data.get("blocked_text", "So funktioniert es noch nicht.")))
		_add_log("", blocked, "action")
		state_changed.emit()
		return {"success": false, "text": blocked}
	var text_value := format_text(str(use_data.get("text", "")))
	_add_log("", text_value, "action")
	var key := location_id + ":" + hotspot_id + ":" + item_id
	_apply_and_complete(use_data.get("effects", {}), key, bool(use_data.get("once", true)))
	inventory.selected_item_id = ""
	return {"success": true, "text": text_value}

func combine_items(first_id: String, second_id: String) -> Dictionary:
	var result := inventory.combine(first_id, second_id)
	_add_log("", format_text(str(result.get("text", ""))), "action")
	if bool(result.get("success", false)):
		puzzles.solve(str(result.get("puzzle_id", "")))
		var result_name := str(inventory.get_item(str(result.get("result", ""))).get("name", "neuer Gegenstand"))
		_add_log("system", "HERGESTELLT: " + result_name, "system")
		save_game()
	state_changed.emit()
	return result

func start_dialogue(dialogue_id: String) -> Dictionary:
	var node := dialogue.start(dialogue_id)
	_log_dialogue_node(node)
	state_changed.emit()
	return get_dialogue_view()

func choose_dialogue(option_id: String) -> Dictionary:
	var node_before := dialogue.current_node()
	var selected: Dictionary = {}
	for option in node_before.get("options", []):
		if str(option.get("id", "")) == option_id and EventCondition.evaluate(option.get("conditions", {}), state, inventory, puzzles):
			selected = option
			break
	if selected.is_empty():
		return {"success": false, "text": "Diese Antwort ist nicht verfügbar."}
	if selected.has("player_text"):
		_add_log(str(state.get("player", {}).get("name", "Du")), format_text(str(selected["player_text"])), "player")
	var chosen := dialogue.choose(option_id)
	_apply_effects(chosen.get("effects", {}))
	if dialogue.is_active():
		_log_dialogue_node(dialogue.current_node())
	else:
		save_game()
	state_changed.emit()
	return {"success": true, "active": dialogue.is_active(), "view": get_dialogue_view()}

func get_dialogue_view() -> Dictionary:
	if not dialogue.is_active():
		return {}
	var node := dialogue.current_node().duplicate(true)
	node["text"] = format_text(str(node.get("text", "")))
	node["options"] = _filter_options(node.get("options", []))
	return node

func save_game() -> bool:
	if state.is_empty():
		return false
	state["rng_state"] = random_events.current_state()
	var payload := {
		"state": state,
		"inventory": inventory.inventory,
		"puzzles": puzzles.solved
	}
	var success := save_manager.save_game(payload)
	save_completed.emit(success)
	return success

func load_game() -> bool:
	var payload := save_manager.load_game()
	return _restore_payload(payload)

func save_checkpoint() -> bool:
	if state.is_empty():
		return false
	state["rng_state"] = random_events.current_state()
	return save_manager.save_checkpoint({
		"state": state,
		"inventory": inventory.inventory,
		"puzzles": puzzles.solved
	})

func load_checkpoint() -> bool:
	return _restore_payload(save_manager.load_checkpoint())

func _restore_payload(payload: Dictionary) -> bool:
	if payload.is_empty() or not payload.has("state"):
		return false
	state = payload["state"]
	inventory.restore(payload.get("inventory", []))
	puzzles.restore(payload.get("puzzles", []))
	dialogue.stop()
	random_events.restore(int(state.get("seed", 1)), int(state.get("rng_state", 0)))
	scene_manager.current_location_id = str(state.get("world", {}).get("current_location", "krankenstation"))
	state_changed.emit()
	return true

func update_settings(new_settings: Dictionary) -> void:
	settings.merge(new_settings, true)
	save_manager.save_settings(settings)
	_apply_audio_settings()
	if bool(settings.get("fullscreen", false)):
		DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_FULLSCREEN)
	else:
		DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_WINDOWED)
	state_changed.emit()

func get_ending_data() -> Dictionary:
	var ending_id := str(state.get("ending", ""))
	var data := story.get_ending(ending_id).duplicate(true)
	if not data.is_empty():
		data["title"] = format_text(str(data.get("title", "")))
		data["text"] = format_text(str(data.get("text", "")))
		var consequences: Array = []
		for line in data.get("consequences", []):
			consequences.append(format_text(str(line)))
		data["consequences"] = consequences
	return data

func format_text(raw_text: String) -> String:
	var player: Dictionary = state.get("player", {})
	var world: Dictionary = state.get("world", {})
	return raw_text.replace("{name}", str(player.get("name", "Mira Vale"))).replace("{pronoun}", str(player.get("subject_pronoun", "sie"))).replace("{hours}", "%.1f" % float(world.get("time_remaining", 72.0)))

func _filter_options(options: Array) -> Array:
	var result: Array = []
	for option in options:
		if EventCondition.evaluate(option.get("conditions", {}), state, inventory, puzzles):
			var view: Dictionary = option.duplicate(true)
			view["label"] = format_text(str(view.get("label", "Weiter")))
			result.append(view)
	return result

func _apply_and_complete(effects: Dictionary, completion_key: String, once: bool) -> void:
	_apply_effects(effects)
	if once:
		var completed: Array = state.get("completed_interactions", [])
		if not completed.has(completion_key):
			completed.append(completion_key)
		state["completed_interactions"] = completed
	save_game()
	state_changed.emit()

func _apply_effects(effects: Dictionary) -> void:
	var feedback := ConsequenceSystem.apply(effects, state, inventory, puzzles)
	for line in feedback:
		_add_log("system", line, "system")

func _trigger_location_event(location: Dictionary) -> void:
	var available: Array = []
	var triggered: Array = state.get("triggered_events", [])
	for event in location.get("random_events", []):
		if not triggered.has(str(event.get("id", ""))) and EventCondition.evaluate(event.get("conditions", {}), state, inventory, puzzles):
			available.append(event)
	if available.is_empty():
		return
	var chosen := random_events.choose_weighted(available)
	var event_id := str(chosen.get("id", ""))
	triggered.append(event_id)
	state["triggered_events"] = triggered
	_add_log("ereignis", format_text(str(chosen.get("text", ""))), "event")
	_apply_effects(chosen.get("effects", {}))
	state["rng_state"] = random_events.current_state()

func _log_dialogue_node(node: Dictionary) -> void:
	if node.is_empty():
		return
	_add_log(str(node.get("speaker", "")), format_text(str(node.get("text", ""))), "dialogue")

func _add_log(speaker: String, text_value: String, kind: String) -> void:
	if state.is_empty() or text_value.strip_edges().is_empty():
		return
	var log: Array = state.get("log", [])
	log.append({"speaker": speaker, "text": text_value, "kind": kind})
	if log.size() > 120:
		log.pop_front()
	state["log"] = log
