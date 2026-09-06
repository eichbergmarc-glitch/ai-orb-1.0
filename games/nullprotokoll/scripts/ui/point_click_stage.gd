class_name PointClickStage
extends Control

## Ego-perspective stage.
##
## The player character is no longer drawn during normal play. Instead the room
## is seen through the character's own eyes: a virtual camera crops into the
## 1920x1080 design canvas, pans while the character walks and pushes in when an
## object is approached. The underlying walk simulation is unchanged, so the
## interaction contract (an action only fires once the approach point has been
## reached) and every existing test still hold.
##
## Story consequences deliberately stay outside this class.

signal hotspot_reached(hotspot_id: String)
signal exit_reached(exit_id: String)
signal viewpoint_changed(design_position: Vector2)

const LAYOUT_PATH := "res://data/spatial_layouts.json"
const DEFAULT_CANVAS_SIZE := Vector2(1920.0, 1080.0)
const DEFAULT_SAFE_RECT := Rect2(0.0, 0.0, 1920.0, 1080.0)
const DEFAULT_WALK_SPEED := 430.0
const DEFAULT_ACTOR_HEIGHT := 310.0
const DEFAULT_FAR_SCALE := 0.58
const DEFAULT_NEAR_SCALE := 1.0
const ARRIVAL_EPSILON := 3.0

# Camera framing. The extent is the fraction of the design canvas that is
# visible; smaller means closer. The source art is 1672 px wide, so the closest
# framing stays well above the point where the upscaling becomes obvious.
const DEFAULT_BASE_EXTENT := 0.86
const MIN_EXTENT := 0.44
const MAX_EXTENT := 1.0
const EYE_LEVEL := 0.455
const PAN_FOLLOW := 0.55
const CAMERA_SMOOTHING := 4.6
const FOCUS_SMOOTHING := 3.2
const LOOK_RANGE := Vector2(52.0, 26.0)
const BOB_AMPLITUDE := 7.5
const BREATH_AMPLITUDE := 3.4

const COLOR_FALLBACK_BG := Color("0a0f14")
const COLOR_WALK_AREA := Color(0.20, 0.78, 0.86, 0.085)
const COLOR_HOTSPOT := Color("63d9e8")
const COLOR_EXIT := Color("d7a744")
const COLOR_SELECTED := Color("f1d486")
const COLOR_TOOLTIP_BG := Color(0.025, 0.04, 0.055, 0.94)
const COLOR_TOOLTIP_BORDER := Color(0.39, 0.85, 0.91, 0.76)
const COLOR_TOOLTIP_TEXT := Color("eef5f3")

const OVERLAY_SHADER := """
shader_type canvas_item;

uniform float vignette_strength : hint_range(0.0, 1.5) = 0.85;
uniform float grain_strength : hint_range(0.0, 0.35) = 0.055;
uniform float time_seed = 0.0;
uniform float breath = 0.0;

float hash21(vec2 p) {
	p = fract(p * vec2(233.34, 851.73));
	p += dot(p, p + 23.45);
	return fract(p.x * p.y);
}

void fragment() {
	vec2 centered = UV - vec2(0.5);
	float radius = length(centered * vec2(1.08, 1.0));
	float vignette = smoothstep(0.42, 0.86, radius) * vignette_strength;
	float grain = (hash21(UV * 720.0 + vec2(time_seed, time_seed * 1.7)) - 0.5) * grain_strength;
	float pulse = breath * 0.04 * smoothstep(0.25, 0.95, radius);
	vec3 tint = vec3(0.015, 0.028, 0.042);
	COLOR = vec4(tint + vec3(grain), clamp(vignette + pulse + abs(grain) * 0.6, 0.0, 0.96));
}
"""

var _layout_document: Dictionary = {}
var _locations: Dictionary = {}
var _layout_loaded := false

var _canvas_size := DEFAULT_CANVAS_SIZE
var _world_safe_rect := DEFAULT_SAFE_RECT
var _location_id := ""
var _layout: Dictionary = {}
var _walk_polygon := PackedVector2Array()
var _baseline := PackedVector2Array()

var _background_texture: Texture2D
var _foreground_texture: Texture2D
var _character_texture: Texture2D
var _texture_cache: Dictionary = {}

var _hotspots: Array[Dictionary] = []
var _exits: Array[Dictionary] = []
var _completed: Dictionary = {}

var _player_position := DEFAULT_CANVAS_SIZE * Vector2(0.5, 0.76)
var _target_position := _player_position
var _moving := false
var _facing_left := false
var _walk_phase := 0.0

var _intent_kind := ""
var _intent_id := ""
var _intent_serial := 0

var _hover_kind := ""
var _hover_id := ""
var _hover_label := ""
var _hover_verb := ""
var _hover_cursor := ""
var _mouse_local := Vector2.ZERO

var _hotspot_mode := false
var _show_hotspot_labels := true
var _input_locked := false
var _reduce_motion := false
var _selected_item_label := ""
var _presentation := "weiblich"
var _state_flags: Dictionary = {}

# Camera state.
var _first_person := true
var _view_center := DEFAULT_CANVAS_SIZE * Vector2(0.5, EYE_LEVEL)
var _view_extent := DEFAULT_BASE_EXTENT
var _look_offset := Vector2.ZERO
var _idle_phase := 0.0
var _bob_phase := 0.0
var _overlay: ColorRect
var _overlay_material: ShaderMaterial


func _ready() -> void:
	clip_contents = true
	mouse_filter = Control.MOUSE_FILTER_STOP
	focus_mode = Control.FOCUS_CLICK
	set_process(true)
	_load_layout_document()
	_build_overlay()
	resized.connect(_on_resized)


func configure(
		location: Dictionary,
		visible_hotspots: Array,
		available_exits: Array,
		completed_interactions: Variant,
		presentation: String,
		state_flags: Variant = []
	) -> void:
	_load_layout_document()

	var next_location_id := str(location.get("id", ""))
	var previous_location_id := _location_id
	var location_changed := next_location_id != _location_id
	var location_needs_loading := location_changed or _layout.is_empty()
	var presentation_changed := presentation != _presentation or _character_texture == null

	_location_id = next_location_id
	_presentation = presentation
	_set_completed(completed_interactions)
	_set_state_flags(state_flags)

	if location_needs_loading:
		_load_location(previous_location_id)
	if presentation_changed:
		_load_character_texture()

	_sync_interactives(visible_hotspots, available_exits)
	if (_intent_kind == "hotspot" and _find_interactive(_hotspots, _intent_id).is_empty()) \
			or (_intent_kind == "exit" and _find_interactive(_exits, _intent_id).is_empty()):
		_cancel_intent(true)
	_update_hover(_mouse_local)
	queue_redraw()


func set_hotspot_mode(enabled: bool) -> void:
	if _hotspot_mode == enabled:
		return
	_hotspot_mode = enabled
	queue_redraw()


func set_show_hotspot_labels(enabled: bool) -> void:
	_show_hotspot_labels = enabled
	queue_redraw()


func set_input_locked(locked: bool) -> void:
	if _input_locked == locked:
		return
	_input_locked = locked
	if locked:
		_cancel_intent(true)
		_clear_hover()
	queue_redraw()


func set_reduce_motion(enabled: bool) -> void:
	_reduce_motion = enabled
	if enabled:
		_look_offset = Vector2.ZERO
	queue_redraw()


func set_selected_item_label(item_label: String) -> void:
	_selected_item_label = item_label.strip_edges()
	queue_redraw()


func set_first_person(enabled: bool) -> void:
	if _first_person == enabled:
		return
	_first_person = enabled
	queue_redraw()


func is_first_person() -> bool:
	return _first_person


func queue_hotspot(hotspot_id: String) -> bool:
	if _input_locked:
		return false
	var hotspot := _find_interactive(_hotspots, hotspot_id)
	if hotspot.is_empty():
		return false
	_begin_intent("hotspot", hotspot_id, hotspot.get("approach", _player_position))
	return true


func queue_exit(exit_id: String) -> bool:
	if _input_locked:
		return false
	var exit_data := _find_interactive(_exits, exit_id)
	if exit_data.is_empty():
		return false
	_begin_intent("exit", exit_id, exit_data.get("approach", _player_position))
	return true


func walk_to(design_position: Vector2) -> void:
	if _input_locked:
		return
	_cancel_intent(false)
	_set_walk_target(_clamp_to_walk_area(design_position))


func get_player_position() -> Vector2:
	return _player_position


func get_interactive_ids() -> Dictionary:
	## Used by the voice command parser to resolve spoken object names.
	var hotspot_entries: Array = []
	for hotspot in _hotspots:
		hotspot_entries.append({"id": str(hotspot.get("id", "")), "label": str(hotspot.get("label", "")), "verb": str(hotspot.get("verb", ""))})
	var exit_entries: Array = []
	for exit_data in _exits:
		exit_entries.append({"id": str(exit_data.get("id", "")), "label": str(exit_data.get("label", "")), "verb": str(exit_data.get("verb", ""))})
	return {"hotspots": hotspot_entries, "exits": exit_entries}


func get_approach_point(kind: String, interaction_id: String) -> Vector2:
	## Vector2.INF meldet "gibt es hier nicht", ohne eine Ausnahme zu erzwingen.
	var collection := _hotspots if kind == "hotspot" else _exits
	var interactive := _find_interactive(collection, interaction_id)
	if interactive.is_empty():
		return Vector2.INF
	return interactive.get("approach", _player_position)


func look_toward(design_position: Vector2) -> void:
	## Turns the view without walking; used by "sieh nach links" style commands.
	if _input_locked:
		return
	_cancel_intent(true)
	var bounds := _walk_bounds()
	_player_position.x = clampf(design_position.x, bounds.position.x, bounds.end.x)
	queue_redraw()


func _process(delta: float) -> void:
	var step_delta := clampf(delta, 0.0, 0.1)
	_advance_walk(step_delta)
	_advance_camera(step_delta)


func _advance_walk(delta: float) -> void:
	if not _moving or _input_locked:
		return

	var offset := _target_position - _player_position
	var distance := offset.length()
	if distance <= ARRIVAL_EPSILON:
		_player_position = _target_position
		_finish_walk()
		return

	var direction := offset / distance
	if absf(direction.x) > 0.03:
		_facing_left = direction.x < 0.0
	var speed := float(_layout.get("walk_speed", DEFAULT_WALK_SPEED))
	var step := minf(speed * delta, distance)
	_player_position += direction * step
	_walk_phase = fmod(_walk_phase + step * 0.045, TAU)
	viewpoint_changed.emit(_player_position)
	queue_redraw()

	if step >= distance - ARRIVAL_EPSILON:
		_player_position = _target_position
		_finish_walk()


func _advance_camera(delta: float) -> void:
	if delta <= 0.0:
		return
	_idle_phase = fmod(_idle_phase + delta, 10000.0)
	if _moving and not _reduce_motion:
		_bob_phase = fmod(_bob_phase + delta * 7.4, TAU)
	else:
		_bob_phase = lerp_angle(_bob_phase, 0.0, minf(1.0, delta * 3.0))

	var desired := _desired_framing()
	var focus_weight := FOCUS_SMOOTHING if _intent_kind.is_empty() else CAMERA_SMOOTHING
	var blend := 1.0 - exp(-focus_weight * delta)
	_view_center = _view_center.lerp(desired["center"], blend)
	_view_extent = lerpf(_view_extent, float(desired["extent"]), blend)

	var look_target := Vector2.ZERO
	if not _reduce_motion and not _input_locked and size.x > 1.0 and size.y > 1.0:
		var normalized := (_mouse_local / size) - Vector2(0.5, 0.5)
		look_target = Vector2(
			clampf(normalized.x, -0.5, 0.5) * 2.0 * LOOK_RANGE.x,
			clampf(normalized.y, -0.5, 0.5) * 2.0 * LOOK_RANGE.y
		)
	_look_offset = _look_offset.lerp(look_target, 1.0 - exp(-5.0 * delta))

	if _overlay_material != null:
		_overlay_material.set_shader_parameter("time_seed", _idle_phase * 37.0)
		_overlay_material.set_shader_parameter("breath", 0.0 if _reduce_motion else sin(_idle_phase * 1.15))
	queue_redraw()


func _desired_framing() -> Dictionary:
	var base_center := Vector2(
		lerpf(_canvas_size.x * 0.5, _player_position.x, PAN_FOLLOW),
		_canvas_size.y * EYE_LEVEL
	)
	if _intent_kind.is_empty():
		return {"center": base_center, "extent": _base_extent()}

	var collection := _hotspots if _intent_kind == "hotspot" else _exits
	var interactive := _find_interactive(collection, _intent_id)
	if interactive.is_empty():
		return {"center": base_center, "extent": _base_extent()}

	var rect: Rect2 = interactive.get("rect", Rect2())
	var focus_extent := _focus_extent_for(rect)
	# Approaching means the framing tightens continuously, so arrival and the
	# push-in end together instead of snapping.
	var travel := _player_position.distance_to(_target_position)
	var progress := 1.0
	if travel > ARRIVAL_EPSILON:
		progress = clampf(1.0 - travel / 620.0, 0.0, 1.0)
	var center := base_center.lerp(rect.get_center(), lerpf(0.35, 1.0, progress))
	var extent := lerpf(_base_extent(), focus_extent, progress)
	return {"center": center, "extent": extent}


func _base_extent() -> float:
	return clampf(float(_layout.get("view_base", DEFAULT_BASE_EXTENT)), MIN_EXTENT, MAX_EXTENT)


func _focus_extent_for(rect: Rect2) -> float:
	if rect.size.x <= 0.0 or rect.size.y <= 0.0:
		return _base_extent()
	var relative := maxf(rect.size.x / _canvas_size.x, rect.size.y / _canvas_size.y)
	return clampf(relative * 2.15, MIN_EXTENT, _base_extent())


func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion:
		_mouse_local = event.position
		_update_hover(_mouse_local)
		return

	if not event is InputEventMouseButton:
		return
	if event.button_index != MOUSE_BUTTON_LEFT or not event.pressed:
		return
	if _input_locked:
		accept_event()
		return

	_mouse_local = event.position
	var design_position := _local_to_design(event.position)
	if not _is_inside_canvas(event.position):
		return

	var hit := _hit_test(design_position)
	if not hit.is_empty():
		var kind := str(hit.get("kind", ""))
		if kind == "hotspot":
			queue_hotspot(str(hit.get("id", "")))
		elif kind == "exit":
			queue_exit(str(hit.get("id", "")))
	else:
		walk_to(design_position)
	accept_event()


func _draw() -> void:
	draw_rect(Rect2(Vector2.ZERO, size), COLOR_FALLBACK_BG)
	var canvas_scale := _canvas_scale()
	var canvas_origin := _canvas_origin(canvas_scale)

	# World layers use stable 1920x1080 design coordinates; only the transform
	# that maps them to the screen changes with the camera.
	draw_set_transform(canvas_origin, 0.0, Vector2.ONE * canvas_scale)
	if _background_texture != null:
		draw_texture_rect(_background_texture, Rect2(Vector2.ZERO, _canvas_size), false)
	else:
		_draw_fallback_background()
	_draw_pickup_visuals()
	if _hotspot_mode and _walk_polygon.size() >= 3:
		draw_colored_polygon(_walk_polygon, COLOR_WALK_AREA)
	draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)

	_draw_scene_actors(canvas_scale, canvas_origin)
	if not _first_person:
		_draw_character(canvas_scale, canvas_origin)

	# A foreground overlay can cover the view (door frames, glass, etc.).
	if _foreground_texture != null:
		draw_set_transform(canvas_origin, 0.0, Vector2.ONE * canvas_scale)
		draw_texture_rect(_foreground_texture, Rect2(Vector2.ZERO, _canvas_size), false)
		draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)

	draw_set_transform(canvas_origin, 0.0, Vector2.ONE * canvas_scale)
	_draw_interactive_outlines()
	draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
	_draw_selected_item_chip()
	_draw_hover_tooltip()


func _build_overlay() -> void:
	if is_instance_valid(_overlay):
		return
	var shader := Shader.new()
	shader.code = OVERLAY_SHADER
	_overlay_material = ShaderMaterial.new()
	_overlay_material.shader = shader
	_overlay_material.set_shader_parameter("vignette_strength", 0.85)
	_overlay_material.set_shader_parameter("grain_strength", 0.055)
	_overlay = ColorRect.new()
	_overlay.name = "ViewOverlay"
	_overlay.color = Color(1.0, 1.0, 1.0, 1.0)
	_overlay.material = _overlay_material
	_overlay.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_overlay)


func _load_layout_document() -> void:
	if _layout_loaded:
		return
	if not FileAccess.file_exists(LAYOUT_PATH):
		# Keep trying on a later configure call; this also makes development-time
		# hot replacement of the spatial data harmless.
		return
	var file := FileAccess.open(LAYOUT_PATH, FileAccess.READ)
	if file == null:
		return
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		push_warning("PointClickStage: Ungueltige Raumdaten in " + LAYOUT_PATH)
		return
	_layout_document = parsed
	_locations = _layout_document.get("locations", {})
	_canvas_size = _vector_from(_layout_document.get("canvas", DEFAULT_CANVAS_SIZE), DEFAULT_CANVAS_SIZE)
	if _canvas_size.x <= 0.0 or _canvas_size.y <= 0.0:
		_canvas_size = DEFAULT_CANVAS_SIZE
	_world_safe_rect = _rect_from(_layout_document.get("world_safe_rect", [0.0, 0.0, _canvas_size.x, _canvas_size.y]), DEFAULT_SAFE_RECT)
	_layout_loaded = true


func _load_location(previous_location_id: String) -> void:
	_cancel_intent(true)
	_clear_hover()
	_layout = _locations.get(_location_id, {})
	_walk_polygon = _polygon_from(_layout.get("walk", []))
	_baseline = _polygon_from(_layout.get("baseline", []))

	var background_path := str(_layout.get("background", ""))
	if background_path.is_empty():
		background_path = "res://assets/backgrounds/%s.png" % _location_id
	_background_texture = _load_texture(background_path)
	_foreground_texture = _load_texture(str(_layout.get("foreground", "")))

	_player_position = _entry_position(previous_location_id)
	_player_position = _clamp_to_walk_area(_player_position)
	_target_position = _player_position
	_moving = false
	_walk_phase = 0.0
	# Entering a room starts from a wide look around rather than a hard cut.
	_view_center = Vector2(
		lerpf(_canvas_size.x * 0.5, _player_position.x, PAN_FOLLOW),
		_canvas_size.y * EYE_LEVEL
	)
	_view_extent = minf(MAX_EXTENT, _base_extent() + 0.1)
	viewpoint_changed.emit(_player_position)


func _load_character_texture() -> void:
	var normalized := _presentation.to_lower()
	var suffix := "male" if normalized in ["maennlich", "männlich", "male", "mann"] else "female"
	_character_texture = _load_texture("res://assets/characters/protagonist_%s.png" % suffix)


func _sync_interactives(visible_hotspots: Array, available_exits: Array) -> void:
	_hotspots.clear()
	_exits.clear()
	var spatial_spots: Dictionary = _layout.get("spots", {})
	var spatial_exits: Dictionary = _layout.get("exits", {})

	for index in range(visible_hotspots.size()):
		var hotspot_value: Variant = visible_hotspots[index]
		if not hotspot_value is Dictionary:
			continue
		var hotspot: Dictionary = hotspot_value
		var hotspot_id := str(hotspot.get("id", ""))
		if hotspot_id.is_empty():
			continue
		var spatial: Dictionary = spatial_spots.get(hotspot_id, {})
		if bool(spatial.get("hide_when_completed", false)) and _is_completed(hotspot_id):
			continue
		_hotspots.append(_make_interactive("hotspot", hotspot, spatial, index, visible_hotspots.size()))

	for index in range(available_exits.size()):
		var exit_value: Variant = available_exits[index]
		if not exit_value is Dictionary:
			continue
		var exit_data: Dictionary = exit_value
		var exit_id := str(exit_data.get("id", ""))
		if exit_id.is_empty():
			continue
		var spatial: Dictionary = spatial_exits.get(exit_id, {})
		_exits.append(_make_interactive("exit", exit_data, spatial, index, available_exits.size()))


func _make_interactive(
		kind: String,
		story_data: Dictionary,
		spatial: Dictionary,
		index: int,
		count: int
	) -> Dictionary:
	var fallback_point := _fallback_interactive_point(index, count, kind)
	var hit_rect := _rect_from(spatial.get("r", spatial.get("rect", [])), Rect2(fallback_point - Vector2(70.0, 90.0), Vector2(140.0, 180.0)))
	var approach := _vector_from(spatial.get("a", spatial.get("approach", fallback_point)), fallback_point)
	return {
		"kind": kind,
		"id": str(story_data.get("id", "")),
		"label": str(story_data.get("label", "Objekt" if kind == "hotspot" else "Weg")),
		"verb": str(story_data.get("verb", "Gehen" if kind == "exit" else "Ansehen")),
		"cursor": str(spatial.get("cursor", "exit" if kind == "exit" else "look")),
		"rect": hit_rect,
		"approach": _clamp_to_walk_area(approach),
		"spatial": spatial
	}


func _begin_intent(kind: String, interaction_id: String, requested_approach: Variant) -> void:
	_intent_serial += 1
	_intent_kind = kind
	_intent_id = interaction_id
	_set_walk_target(_clamp_to_walk_area(_vector_from(requested_approach, _player_position)))
	if not _moving:
		# Defer so a zero-distance click behaves like a normal completed walk and
		# cannot mutate the UI in the middle of its input dispatch.
		var serial := _intent_serial
		call_deferred("_complete_intent_if_current", serial)


func _set_walk_target(target: Vector2) -> void:
	_target_position = target
	_moving = _player_position.distance_to(_target_position) > ARRIVAL_EPSILON
	if not _moving:
		_player_position = _target_position
	queue_redraw()


func _finish_walk() -> void:
	_moving = false
	_walk_phase = 0.0
	viewpoint_changed.emit(_player_position)
	queue_redraw()
	_complete_intent_if_current(_intent_serial)


func _complete_intent_if_current(serial: int) -> void:
	if serial != _intent_serial or _moving or _input_locked:
		return
	var kind := _intent_kind
	var interaction_id := _intent_id
	_intent_kind = ""
	_intent_id = ""
	if interaction_id.is_empty():
		return
	if kind == "hotspot":
		hotspot_reached.emit(interaction_id)
	elif kind == "exit":
		exit_reached.emit(interaction_id)


func _cancel_intent(stop_walking: bool) -> void:
	_intent_serial += 1
	_intent_kind = ""
	_intent_id = ""
	if stop_walking:
		_moving = false
		_target_position = _player_position
		_walk_phase = 0.0


func _hit_test(design_position: Vector2) -> Dictionary:
	var best: Dictionary = {}
	var best_area := INF
	for interactive in _hotspots + _exits:
		var rect: Rect2 = interactive.get("rect", Rect2())
		if rect.has_point(design_position):
			var area := rect.size.x * rect.size.y
			if area < best_area:
				best = interactive
				best_area = area
	return best


func _update_hover(local_position: Vector2) -> void:
	if _input_locked or not _is_inside_canvas(local_position):
		_clear_hover()
		return
	var hit := _hit_test(_local_to_design(local_position))
	var next_kind := str(hit.get("kind", ""))
	var next_id := str(hit.get("id", ""))
	if next_kind == _hover_kind and next_id == _hover_id:
		return
	_hover_kind = next_kind
	_hover_id = next_id
	_hover_label = str(hit.get("label", ""))
	_hover_verb = str(hit.get("verb", ""))
	_hover_cursor = str(hit.get("cursor", ""))
	mouse_default_cursor_shape = _cursor_shape(_hover_cursor) if not hit.is_empty() else Control.CURSOR_MOVE
	queue_redraw()


func _clear_hover() -> void:
	_hover_kind = ""
	_hover_id = ""
	_hover_label = ""
	_hover_verb = ""
	_hover_cursor = ""
	mouse_default_cursor_shape = Control.CURSOR_ARROW if _input_locked else Control.CURSOR_MOVE
	queue_redraw()


func _tooltip_text() -> String:
	if _hover_label.is_empty():
		return ""
	if not _selected_item_label.is_empty() and _hover_kind == "hotspot":
		return "%s → %s" % [_selected_item_label, _hover_label]
	if not _show_hotspot_labels:
		return ""
	return "%s · %s" % [_hover_verb, _hover_label]


func _draw_interactive_outlines() -> void:
	var index := 0
	for interactive in _hotspots + _exits:
		index += 1
		var hovered := str(interactive.get("kind", "")) == _hover_kind and str(interactive.get("id", "")) == _hover_id
		var intended := str(interactive.get("kind", "")) == _intent_kind and str(interactive.get("id", "")) == _intent_id
		if not _hotspot_mode and not hovered and not intended:
			continue
		var kind := str(interactive.get("kind", ""))
		var color := COLOR_EXIT if kind == "exit" else COLOR_HOTSPOT
		if intended or (not _selected_item_label.is_empty() and kind == "hotspot"):
			color = COLOR_SELECTED
		var rect: Rect2 = interactive.get("rect", Rect2())
		if _first_person:
			_draw_focus_frame(rect, color, hovered or intended, index if _hotspot_mode else 0)
		else:
			var width := 4.0 if hovered or intended else 2.0
			draw_rect(rect, Color(color, 0.075 if _hotspot_mode else 0.045), true)
			draw_rect(rect, Color(color, 0.94 if hovered or intended else 0.60), false, width)
			draw_circle(rect.get_center(), 8.0 if hovered else 5.0, color)
			if intended:
				draw_dashed_line(_player_position, interactive.get("approach", rect.get_center()), Color(color, 0.55), 2.0, 10.0)


func _draw_focus_frame(rect: Rect2, color: Color, strong: bool, number: int) -> void:
	## Corner ticks read as a camera focus frame instead of a UI rectangle, which
	## keeps the first-person view from looking like a diagram.
	var alpha := 0.92 if strong else 0.48
	var arm := clampf(minf(rect.size.x, rect.size.y) * 0.22, 12.0, 46.0)
	var width := 3.0 if strong else 2.0
	var corners := [
		[rect.position, Vector2(1.0, 0.0), Vector2(0.0, 1.0)],
		[Vector2(rect.end.x, rect.position.y), Vector2(-1.0, 0.0), Vector2(0.0, 1.0)],
		[Vector2(rect.position.x, rect.end.y), Vector2(1.0, 0.0), Vector2(0.0, -1.0)],
		[rect.end, Vector2(-1.0, 0.0), Vector2(0.0, -1.0)]
	]
	for corner in corners:
		var origin: Vector2 = corner[0]
		draw_line(origin, origin + (corner[1] as Vector2) * arm, Color(color, alpha), width)
		draw_line(origin, origin + (corner[2] as Vector2) * arm, Color(color, alpha), width)
	if strong:
		draw_rect(rect, Color(color, 0.06), true)
	if number > 0:
		var font := get_theme_default_font()
		var font_size := 26
		var badge := rect.position + Vector2(rect.size.x * 0.5, -14.0)
		draw_circle(badge, 19.0, Color(0.02, 0.05, 0.07, 0.86))
		draw_arc(badge, 19.0, 0.0, TAU, 24, Color(color, 0.9), 2.0)
		draw_string(font, badge + Vector2(-7.0, 9.0), str(number), HORIZONTAL_ALIGNMENT_LEFT, -1.0, font_size, Color(color, 0.98))


func _draw_pickup_visuals() -> void:
	var visuals: Variant = _layout.get("pickup_visuals", [])
	if not visuals is Array:
		return
	for value in visuals:
		if not value is Dictionary:
			continue
		var visual: Dictionary = value
		var interaction_id := str(visual.get("hotspot", visual.get("id", "")))
		if _pickup_visual_is_hidden(visual, interaction_id):
			continue
		var path := str(visual.get("texture", visual.get("sprite", visual.get("image", ""))))
		var texture := _load_texture(path)
		if texture == null:
			_draw_pickup_glimmer(_vector_from(visual.get("anchor", visual.get("p", [])), Vector2.ZERO))
			continue
		var texture_size := Vector2(texture.get_width(), texture.get_height())
		var target_rect := _rect_from(visual.get("r", visual.get("rect", [])), Rect2())
		if target_rect.size.x <= 0.0 or target_rect.size.y <= 0.0:
			var position := _vector_from(visual.get("p", visual.get("anchor", [])), Vector2.ZERO)
			var draw_size := _vector_from(visual.get("size", texture_size), texture_size)
			target_rect = Rect2(position - draw_size * Vector2(0.5, 1.0), draw_size)
		draw_texture_rect(texture, target_rect, false)


func _pickup_visual_is_hidden(visual: Dictionary, interaction_id: String) -> bool:
	var hide_when := str(visual.get("hide_when", ""))
	if hide_when.begins_with("completed:"):
		return _completed.has(hide_when.trim_prefix("completed:"))
	if hide_when.begins_with("flag:"):
		return _state_flags.has(hide_when.trim_prefix("flag:"))
	return bool(visual.get("hide_when_completed", not interaction_id.is_empty())) and _is_completed(interaction_id)


func _draw_pickup_glimmer(anchor: Vector2) -> void:
	if anchor == Vector2.ZERO:
		return
	var pulse := 1.0 if _reduce_motion else 0.72 + 0.28 * sin(_idle_phase * 2.1)
	var strength := (0.72 if _hotspot_mode else 0.26) * pulse
	var radius := 14.0 if _hotspot_mode else 8.0
	draw_circle(anchor, radius * 0.36, Color(COLOR_EXIT, strength * 0.78))
	draw_arc(anchor, radius, -0.35, PI + 0.45, 18, Color(COLOR_HOTSPOT, strength), 2.0)
	draw_line(anchor - Vector2(radius * 0.72, 0.0), anchor + Vector2(radius * 0.72, 0.0), Color(COLOR_HOTSPOT, strength * 0.60), 1.0)
	draw_line(anchor - Vector2(0.0, radius * 0.72), anchor + Vector2(0.0, radius * 0.72), Color(COLOR_EXIT, strength * 0.60), 1.0)


func _draw_scene_actors(canvas_scale: float, canvas_origin: Vector2) -> void:
	var actor_values: Variant = _layout.get("actors", [])
	if not actor_values is Array:
		return
	for actor_value in actor_values:
		if not actor_value is Dictionary:
			continue
		var actor: Dictionary = actor_value
		if not _scene_actor_is_visible(actor):
			continue
		var texture := _load_texture(str(actor.get("texture", "")))
		if texture == null or texture.get_height() <= 0:
			continue

		var foot_design := _vector_from(actor.get("p", []), Vector2.ZERO)
		var depth_scale := _actor_depth_scale(foot_design)
		var actor_height := maxf(1.0, float(actor.get("height", DEFAULT_ACTOR_HEIGHT))) * depth_scale * canvas_scale
		var actor_width := actor_height * float(texture.get_width()) / float(texture.get_height())
		var foot_local := canvas_origin + foot_design * canvas_scale
		var flip := -1.0 if bool(actor.get("flip_h", false)) else 1.0
		var tint := _color_from(actor.get("tint", Color.WHITE), Color.WHITE)

		var shadow_width := actor_width * 0.46
		var shadow_height := maxf(4.0, actor_height * 0.035)
		draw_colored_polygon(
			_ellipse_polygon(foot_local + Vector2(0.0, 1.5 * canvas_scale), shadow_width, shadow_height),
			Color(0.0, 0.0, 0.0, 0.40 * tint.a)
		)
		draw_set_transform(foot_local, 0.0, Vector2(flip, 1.0))
		draw_texture_rect(texture, Rect2(-actor_width * 0.5, -actor_height, actor_width, actor_height), false, tint)
		draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)


func _scene_actor_is_visible(actor: Dictionary) -> bool:
	for required_flag in _string_values(actor.get("visible_flags_all", [])):
		if not _state_flags.has(required_flag):
			return false
	for excluded_flag in _string_values(actor.get("visible_flags_none", [])):
		if _state_flags.has(excluded_flag):
			return false
	return true


func _draw_character(canvas_scale: float, canvas_origin: Vector2) -> void:
	var depth_scale := _actor_depth_scale(_player_position)
	var bob_design := sin(_walk_phase * 2.0) * 4.2 * depth_scale if _moving and not _reduce_motion else 0.0
	var foot_local := canvas_origin + _player_position * canvas_scale
	var actor_height := float(_layout.get("actor_height", DEFAULT_ACTOR_HEIGHT)) * depth_scale * canvas_scale
	var actor_width := actor_height * 0.40
	if _character_texture != null and _character_texture.get_height() > 0:
		actor_width = actor_height * float(_character_texture.get_width()) / float(_character_texture.get_height())

	var shadow_width := actor_width * 0.46
	var shadow_height := maxf(4.0, actor_height * 0.035)
	var shadow_center := foot_local + Vector2(0.0, 1.5 * canvas_scale)
	draw_colored_polygon(_ellipse_polygon(shadow_center, shadow_width, shadow_height), Color(0.0, 0.0, 0.0, 0.48))

	var bob_local := bob_design * canvas_scale
	var tilt := sin(_walk_phase) * 0.012 if _moving and not _reduce_motion else 0.0
	var flip := -1.0 if _facing_left else 1.0
	if _character_texture != null:
		draw_set_transform(foot_local - Vector2(0.0, bob_local), tilt, Vector2(flip, 1.0))
		draw_texture_rect(_character_texture, Rect2(-actor_width * 0.5, -actor_height, actor_width, actor_height), false)
		draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
	else:
		_draw_fallback_character(foot_local - Vector2(0.0, bob_local), actor_height)


func _draw_fallback_character(foot: Vector2, actor_height: float) -> void:
	var body_color := Color("aebbc0")
	var dark := Color("27343d")
	var head_radius := actor_height * 0.075
	var head := foot - Vector2(0.0, actor_height * 0.79)
	draw_circle(head, head_radius, Color("c58d6b"))
	draw_line(head + Vector2(0.0, head_radius), foot - Vector2(0.0, actor_height * 0.30), body_color, actor_height * 0.12, true)
	var stride := sin(_walk_phase) * actor_height * 0.065 if _moving else actor_height * 0.025
	var hip := foot - Vector2(0.0, actor_height * 0.31)
	draw_line(hip, foot + Vector2(stride, 0.0), dark, actor_height * 0.055, true)
	draw_line(hip, foot - Vector2(stride, 0.0), dark, actor_height * 0.055, true)


func _draw_fallback_background() -> void:
	draw_rect(Rect2(Vector2.ZERO, _canvas_size), COLOR_FALLBACK_BG)
	var grid_color := Color(0.24, 0.38, 0.44, 0.13)
	for x in range(0, int(_canvas_size.x) + 1, 96):
		draw_line(Vector2(x, 0.0), Vector2(x, _canvas_size.y), grid_color, 1.0)
	for y in range(0, int(_canvas_size.y) + 1, 96):
		draw_line(Vector2(0.0, y), Vector2(_canvas_size.x, y), grid_color, 1.0)
	if _walk_polygon.size() >= 3:
		draw_colored_polygon(_walk_polygon, Color(0.12, 0.18, 0.22, 0.70))


func _draw_selected_item_chip() -> void:
	if _selected_item_label.is_empty():
		return
	var font := get_theme_default_font()
	var font_size := maxi(get_theme_default_font_size(), 17)
	var label_text := "BENUTZEN: " + _selected_item_label
	var text_size := font.get_string_size(label_text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size)
	var chip := Rect2(Vector2(18.0, 18.0), text_size + Vector2(30.0, 20.0))
	draw_rect(chip, COLOR_TOOLTIP_BG, true)
	draw_rect(chip, Color(COLOR_SELECTED, 0.82), false, 2.0)
	draw_string(font, chip.position + Vector2(15.0, 14.0 + text_size.y * 0.72), label_text, HORIZONTAL_ALIGNMENT_LEFT, -1.0, font_size, COLOR_SELECTED)


func _draw_hover_tooltip() -> void:
	var label_text := _tooltip_text()
	if label_text.is_empty() or _input_locked:
		return
	var font := get_theme_default_font()
	var font_size := maxi(get_theme_default_font_size(), 18)
	var text_size := font.get_string_size(label_text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size)
	var tooltip_size := text_size + Vector2(28.0, 20.0)
	var position := _mouse_local + Vector2(18.0, 22.0)
	position.x = clampf(position.x, 8.0, maxf(8.0, size.x - tooltip_size.x - 8.0))
	position.y = clampf(position.y, 8.0, maxf(8.0, size.y - tooltip_size.y - 8.0))
	var tooltip_rect := Rect2(position, tooltip_size)
	draw_rect(tooltip_rect, COLOR_TOOLTIP_BG, true)
	draw_rect(tooltip_rect, COLOR_TOOLTIP_BORDER, false, 2.0)
	draw_string(font, position + Vector2(14.0, 13.0 + text_size.y * 0.72), label_text, HORIZONTAL_ALIGNMENT_LEFT, -1.0, font_size, COLOR_TOOLTIP_TEXT)


func _actor_depth_scale(position: Vector2) -> float:
	var far_scale := float(_layout.get("far_scale", DEFAULT_FAR_SCALE))
	var near_scale := float(_layout.get("near_scale", DEFAULT_NEAR_SCALE))
	var far_y := _walk_bounds().position.y
	var front_y := _baseline_y_at(position.x)
	if front_y <= far_y + 1.0:
		front_y = _walk_bounds().end.y
	var depth := clampf(inverse_lerp(far_y, front_y, position.y), 0.0, 1.0)
	return lerpf(far_scale, near_scale, depth)


func _baseline_y_at(x: float) -> float:
	if _baseline.size() < 2:
		return _walk_bounds().end.y
	var left := _baseline[0]
	var right := _baseline[_baseline.size() - 1]
	if absf(right.x - left.x) < 0.001:
		return maxf(left.y, right.y)
	var t := clampf((x - left.x) / (right.x - left.x), 0.0, 1.0)
	return lerpf(left.y, right.y, t)


func _entry_position(previous_location_id: String) -> Vector2:
	var entries: Variant = _layout.get("entries", {})
	if entries is Dictionary and not entries.is_empty():
		var previous_key := "from_" + previous_location_id
		if not previous_location_id.is_empty() and entries.has(previous_key):
			return _vector_from(entries[previous_key], _walk_center())
		if entries.has("start"):
			return _vector_from(entries["start"], _walk_center())
		for value in entries.values():
			return _vector_from(value, _walk_center())
	return _walk_center()


func _clamp_to_walk_area(point: Vector2) -> Vector2:
	if _walk_polygon.size() < 3:
		return _clamp_to_rect(point, _world_safe_rect)
	if Geometry2D.is_point_in_polygon(point, _walk_polygon):
		return point
	var closest := _walk_polygon[0]
	var closest_distance_squared := INF
	for index in range(_walk_polygon.size()):
		var a := _walk_polygon[index]
		var b := _walk_polygon[(index + 1) % _walk_polygon.size()]
		var candidate := _closest_point_on_segment(point, a, b)
		var candidate_distance_squared := point.distance_squared_to(candidate)
		if candidate_distance_squared < closest_distance_squared:
			closest = candidate
			closest_distance_squared = candidate_distance_squared
	return closest


func _closest_point_on_segment(point: Vector2, segment_start: Vector2, segment_end: Vector2) -> Vector2:
	var segment := segment_end - segment_start
	var length_squared := segment.length_squared()
	if length_squared <= 0.0001:
		return segment_start
	var t := clampf((point - segment_start).dot(segment) / length_squared, 0.0, 1.0)
	return segment_start + segment * t


func _walk_center() -> Vector2:
	if _walk_polygon.is_empty():
		return _world_safe_rect.get_center()
	var total := Vector2.ZERO
	for point in _walk_polygon:
		total += point
	return total / float(_walk_polygon.size())


func _walk_bounds() -> Rect2:
	if _walk_polygon.is_empty():
		return _world_safe_rect
	var minimum := _walk_polygon[0]
	var maximum := _walk_polygon[0]
	for point in _walk_polygon:
		minimum.x = minf(minimum.x, point.x)
		minimum.y = minf(minimum.y, point.y)
		maximum.x = maxf(maximum.x, point.x)
		maximum.y = maxf(maximum.y, point.y)
	return Rect2(minimum, maximum - minimum)


func _fallback_interactive_point(index: int, count: int, kind: String) -> Vector2:
	var bounds := _walk_bounds()
	var divisor := float(maxi(count + 1, 2))
	var x := bounds.position.x + bounds.size.x * float(index + 1) / divisor
	if kind == "exit":
		x = bounds.position.x if index % 2 == 0 else bounds.end.x
	return _clamp_to_walk_area(Vector2(x, bounds.position.y + bounds.size.y * 0.55))


func _find_interactive(collection: Array[Dictionary], interaction_id: String) -> Dictionary:
	for interactive in collection:
		if str(interactive.get("id", "")) == interaction_id:
			return interactive
	return {}


func _set_completed(value: Variant) -> void:
	_completed.clear()
	if value is Dictionary:
		for key in value:
			if bool(value[key]):
				_completed[str(key)] = true
	elif value is Array or value is PackedStringArray:
		for key in value:
			_completed[str(key)] = true


func _set_state_flags(value: Variant) -> void:
	_state_flags.clear()
	if value is Dictionary:
		for key in value:
			if bool(value[key]):
				_state_flags[str(key)] = true
	elif value is Array or value is PackedStringArray:
		for key in value:
			_state_flags[str(key)] = true


func _is_completed(interaction_id: String) -> bool:
	return _completed.has(interaction_id) or _completed.has(_location_id + ":" + interaction_id)


func _load_texture(path: String) -> Texture2D:
	if path.is_empty():
		return null
	if _texture_cache.has(path):
		return _texture_cache[path]
	if not ResourceLoader.exists(path):
		return null
	var resource := ResourceLoader.load(path)
	if resource is Texture2D:
		_texture_cache[path] = resource
		return resource
	return null


func _polygon_from(value: Variant) -> PackedVector2Array:
	var result := PackedVector2Array()
	if value is Array:
		for entry in value:
			result.append(_vector_from(entry, Vector2.ZERO))
	return result


func _vector_from(value: Variant, fallback: Vector2) -> Vector2:
	if value is Vector2:
		return value
	if value is Array and value.size() >= 2:
		return Vector2(float(value[0]), float(value[1]))
	if value is Dictionary and value.has("x") and value.has("y"):
		return Vector2(float(value["x"]), float(value["y"]))
	return fallback


func _color_from(value: Variant, fallback: Color) -> Color:
	if value is Color:
		return value
	if not value is Array or value.size() < 3:
		return fallback
	var red := float(value[0])
	var green := float(value[1])
	var blue := float(value[2])
	var alpha := float(value[3]) if value.size() >= 4 else 1.0
	if maxf(maxf(red, green), maxf(blue, alpha)) > 1.0:
		red /= 255.0
		green /= 255.0
		blue /= 255.0
		alpha /= 255.0
	return Color(clampf(red, 0.0, 1.0), clampf(green, 0.0, 1.0), clampf(blue, 0.0, 1.0), clampf(alpha, 0.0, 1.0))


func _string_values(value: Variant) -> Array[String]:
	var result: Array[String] = []
	if value is Array or value is PackedStringArray:
		for entry in value:
			result.append(str(entry))
	elif value is String and not value.is_empty():
		result.append(value)
	return result


func _rect_from(value: Variant, fallback: Rect2) -> Rect2:
	if value is Rect2:
		return value.abs()
	if value is Array:
		if value.size() >= 4:
			return Rect2(float(value[0]), float(value[1]), float(value[2]), float(value[3])).abs()
		if value.size() >= 2:
			var center := _vector_from(value, fallback.get_center())
			return Rect2(center - fallback.size * 0.5, fallback.size)
	if value is Dictionary:
		var position := _vector_from(value.get("position", value.get("p", [])), fallback.position)
		var rect_size := _vector_from(value.get("size", value.get("s", [])), fallback.size)
		return Rect2(position, rect_size).abs()
	return fallback


func _clamp_to_rect(point: Vector2, rect: Rect2) -> Vector2:
	return Vector2(
		clampf(point.x, rect.position.x, rect.end.x),
		clampf(point.y, rect.position.y, rect.end.y)
	)


func _cursor_shape(cursor_id: String) -> CursorShape:
	match cursor_id.to_lower():
		"take": return Control.CURSOR_DRAG
		"talk": return Control.CURSOR_POINTING_HAND
		"use": return Control.CURSOR_CROSS
		"look": return Control.CURSOR_HELP
		"exit": return Control.CURSOR_POINTING_HAND
		_: return Control.CURSOR_POINTING_HAND


func _ellipse_polygon(center: Vector2, radius_x: float, radius_y: float) -> PackedVector2Array:
	var points := PackedVector2Array()
	for index in range(24):
		var angle := TAU * float(index) / 24.0
		points.append(center + Vector2(cos(angle) * radius_x, sin(angle) * radius_y))
	return points


func _camera_offset() -> Vector2:
	if _reduce_motion:
		return Vector2.ZERO
	var bob := Vector2(0.0, sin(_bob_phase) * BOB_AMPLITUDE) if _moving else Vector2.ZERO
	var sway := Vector2(sin(_bob_phase * 0.5) * BOB_AMPLITUDE * 0.45, 0.0) if _moving else Vector2.ZERO
	var breath := Vector2(
		sin(_idle_phase * 0.41) * BREATH_AMPLITUDE * 0.6,
		sin(_idle_phase * 1.15) * BREATH_AMPLITUDE
	)
	return bob + sway + breath + _look_offset


func _visible_rect() -> Rect2:
	var extent := clampf(_view_extent, MIN_EXTENT, MAX_EXTENT)
	var view_size := _canvas_size * extent
	var half := view_size * 0.5
	var center := _view_center + _camera_offset()
	center.x = clampf(center.x, half.x, maxf(half.x, _canvas_size.x - half.x))
	center.y = clampf(center.y, half.y, maxf(half.y, _canvas_size.y - half.y))
	return Rect2(center - half, view_size)


func _canvas_scale() -> float:
	if _canvas_size.x <= 0.0 or _canvas_size.y <= 0.0:
		return 1.0
	if not _first_person:
		return maxf(0.0001, minf(size.x / _canvas_size.x, size.y / _canvas_size.y))
	var view_size := _visible_rect().size
	if view_size.x <= 0.0 or view_size.y <= 0.0:
		return 1.0
	# Cover rather than fit: the crop always fills the panel, no letterboxing.
	return maxf(0.0001, maxf(size.x / view_size.x, size.y / view_size.y))


func _canvas_origin(canvas_scale: float) -> Vector2:
	if not _first_person:
		return (size - _canvas_size * canvas_scale) * 0.5
	return size * 0.5 - _visible_rect().get_center() * canvas_scale


func local_to_design(local_position: Vector2) -> Vector2:
	## Bildpunkt zu Weltpunkt, oeffentlich fuer Tests und Werkzeuge.
	return _local_to_design(local_position)


func design_to_local(design_position: Vector2) -> Vector2:
	## Umkehrung von _local_to_design. Tests und Sprachbefehle koennen damit
	## einen Weltpunkt anklicken, ohne die Kameramathematik zu kennen.
	var scale := _canvas_scale()
	return _canvas_origin(scale) + design_position * scale


func _local_to_design(local_position: Vector2) -> Vector2:
	var scale := _canvas_scale()
	return (local_position - _canvas_origin(scale)) / scale


func _is_inside_canvas(local_position: Vector2) -> bool:
	if not _first_person:
		var scale := _canvas_scale()
		return Rect2(_canvas_origin(scale), _canvas_size * scale).has_point(local_position)
	return Rect2(Vector2.ZERO, size).has_point(local_position)


func _on_resized() -> void:
	_update_hover(_mouse_local)
	queue_redraw()
