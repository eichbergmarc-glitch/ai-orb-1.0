class_name NPCutsceneLayer
extends Control

## Cutscenes are the only place the player character is seen.
##
## During play the camera sits behind the character's eyes, so the figure itself
## only appears at story beats: waking up, meeting Juna, the decisions that
## change who the character has become, and the endings. Portraits are drawn
## large on purpose, filling most of the frame, because at that moment the
## person is the subject rather than the room.

signal beat_started(beat: Dictionary)
signal finished(trigger_id: String)

const DATA_PATH := "res://data/cutscenes.json"
const PORTRAIT_HEIGHT_RATIO := 0.94
const FADE_SECONDS := 0.55

var _document: Dictionary = {}
var _loaded := false

var _dim: ColorRect
var _room: TextureRect
var _portrait: TextureRect
var _caption_panel: PanelContainer
var _speaker_label: Label
var _caption_label: RichTextLabel
var _prompt_label: Label

var _sequence: Array = []
var _index := -1
var _trigger_id := ""
var _presentation := "weiblich"
var _texture_cache: Dictionary = {}
var _accepting := false


func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_STOP
	visible = false
	_build()
	resized.connect(_layout_portrait)


func _build() -> void:
	_room = TextureRect.new()
	_room.name = "RoomStill"
	_room.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_room.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	_room.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_room.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_room)

	_dim = ColorRect.new()
	_dim.name = "Dim"
	_dim.color = Color(0.012, 0.02, 0.032, 0.82)
	_dim.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_dim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_dim)

	_portrait = TextureRect.new()
	_portrait.name = "Portrait"
	_portrait.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_portrait.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT
	_portrait.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_portrait)

	_caption_panel = PanelContainer.new()
	_caption_panel.name = "Caption"
	_caption_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_caption_panel.add_theme_stylebox_override(
		"panel",
		NPUIManager.panel_style(Color(0.02, 0.035, 0.05, 0.94), NPUIManager.BORDER, 10, 1)
	)
	_caption_panel.set_anchors_preset(Control.PRESET_BOTTOM_WIDE)
	_caption_panel.offset_left = 90.0
	_caption_panel.offset_right = -90.0
	_caption_panel.offset_top = -260.0
	_caption_panel.offset_bottom = -60.0
	add_child(_caption_panel)

	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 10)
	_caption_panel.add_child(column)

	_speaker_label = Label.new()
	_speaker_label.add_theme_color_override("font_color", NPUIManager.ACCENT)
	_speaker_label.add_theme_font_size_override("font_size", 22)
	column.add_child(_speaker_label)

	_caption_label = RichTextLabel.new()
	_caption_label.bbcode_enabled = false
	_caption_label.fit_content = true
	_caption_label.scroll_active = false
	_caption_label.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_caption_label.add_theme_font_size_override("normal_font_size", 30)
	_caption_label.add_theme_color_override("default_color", NPUIManager.TEXT)
	column.add_child(_caption_label)

	_prompt_label = Label.new()
	_prompt_label.text = "Klick, Leertaste oder „weiter“ sagen"
	_prompt_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	_prompt_label.add_theme_color_override("font_color", NPUIManager.MUTED)
	_prompt_label.add_theme_font_size_override("font_size", 17)
	column.add_child(_prompt_label)


func set_presentation(value: String) -> void:
	_presentation = value


func has_sequence(trigger_id: String) -> bool:
	_load_document()
	return _document.has(trigger_id)


func play(trigger_id: String) -> bool:
	_load_document()
	var sequence: Variant = _document.get(trigger_id, [])
	if not sequence is Array or sequence.is_empty():
		return false
	_sequence = sequence
	_trigger_id = trigger_id
	_index = -1
	visible = true
	modulate = Color(1.0, 1.0, 1.0, 0.0)
	var tween := create_tween()
	tween.tween_property(self, "modulate:a", 1.0, FADE_SECONDS)
	advance()
	return true


func is_playing() -> bool:
	return visible and _index >= 0


func advance() -> void:
	_index += 1
	if _index >= _sequence.size():
		_close()
		return
	var beat_value: Variant = _sequence[_index]
	if not beat_value is Dictionary:
		advance()
		return
	var beat: Dictionary = beat_value
	_apply_beat(beat)
	_accepting = false
	# A short guard keeps a double click from skipping two beats at once.
	get_tree().create_timer(0.28).timeout.connect(func() -> void: _accepting = true)
	beat_started.emit(beat)


func _apply_beat(beat: Dictionary) -> void:
	var background_id := str(beat.get("background", ""))
	if background_id.is_empty():
		_room.texture = null
	else:
		_room.texture = _texture("res://assets/backgrounds/%s.png" % background_id)
	_dim.color = Color(0.012, 0.02, 0.032, float(beat.get("dim", 0.82)))

	var character := str(beat.get("character", ""))
	_portrait.texture = _portrait_texture(character)
	_portrait.flip_h = bool(beat.get("flip", false))
	_layout_portrait()

	_speaker_label.text = str(beat.get("speaker", "")).to_upper()
	_speaker_label.visible = not _speaker_label.text.is_empty()
	_caption_label.text = str(beat.get("text", ""))


func _portrait_texture(character: String) -> Texture2D:
	match character.to_lower():
		"", "none", "keine":
			return null
		"juna", "juna_falk":
			return _texture("res://assets/characters/juna_falk.png")
		"protagonist", "spieler", "ich":
			var normalized := _presentation.to_lower()
			var suffix := "male" if normalized in ["maennlich", "männlich", "male", "mann"] else "female"
			return _texture("res://assets/characters/protagonist_%s.png" % suffix)
		_:
			return _texture("res://assets/characters/%s.png" % character.to_lower())


func _layout_portrait() -> void:
	if not is_instance_valid(_portrait):
		return
	var texture := _portrait.texture
	if texture == null or texture.get_height() <= 0:
		_portrait.size = Vector2.ZERO
		return
	var target_height := size.y * PORTRAIT_HEIGHT_RATIO
	var target_width := target_height * float(texture.get_width()) / float(texture.get_height())
	_portrait.size = Vector2(target_width, target_height)
	_portrait.position = Vector2((size.x - target_width) * 0.5, size.y - target_height)


func _gui_input(event: InputEvent) -> void:
	if not visible or not _accepting:
		return
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		accept_event()
		advance()


func handle_key() -> bool:
	if not visible or not _accepting:
		return false
	advance()
	return true


func _close() -> void:
	_index = -1
	_sequence = []
	var tween := create_tween()
	tween.tween_property(self, "modulate:a", 0.0, FADE_SECONDS)
	tween.tween_callback(func() -> void: visible = false)
	finished.emit(_trigger_id)


func _texture(path: String) -> Texture2D:
	if _texture_cache.has(path):
		return _texture_cache[path]
	if not ResourceLoader.exists(path):
		_texture_cache[path] = null
		return null
	var resource := ResourceLoader.load(path)
	var texture := resource as Texture2D
	_texture_cache[path] = texture
	return texture


func _load_document() -> void:
	if _loaded:
		return
	_loaded = true
	if not FileAccess.file_exists(DATA_PATH):
		return
	var file := FileAccess.open(DATA_PATH, FileAccess.READ)
	if file == null:
		return
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if parsed is Dictionary:
		_document = parsed.get("sequences", parsed)
