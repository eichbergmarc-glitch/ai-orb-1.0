class_name SceneBackdrop
extends Control

var location_id := "title"
var palette_id := "title"
var scene_title := "NULLPROTOKOLL"
var reduce_motion := false
var hotspots_visible := true
var scan_position := 0.0

func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_process(true)

func set_scene(location: Dictionary, reduced := false) -> void:
	location_id = str(location.get("id", "title"))
	palette_id = str(location.get("palette", "title"))
	scene_title = str(location.get("title", "NULLPROTOKOLL"))
	reduce_motion = reduced
	queue_redraw()

func set_title_scene() -> void:
	location_id = "title"
	palette_id = "title"
	scene_title = "NULLPROTOKOLL"
	queue_redraw()

func _process(delta: float) -> void:
	if reduce_motion:
		return
	scan_position = fmod(scan_position + delta * 42.0, maxf(size.y, 1.0))
	queue_redraw()

func _draw() -> void:
	var rect := Rect2(Vector2.ZERO, size)
	draw_rect(rect, Color("090c11"))
	_draw_grid()
	match palette_id:
		"medical": _draw_medical()
		"diagnostic": _draw_diagnostic()
		"security": _draw_security()
		"maintenance": _draw_maintenance()
		"quarantine": _draw_quarantine()
		"archive": _draw_archive()
		"uplink": _draw_uplink()
		_: _draw_title()
	_draw_vignette()
	if not reduce_motion:
		draw_rect(Rect2(0, scan_position, size.x, 2), Color(0.39, 0.85, 0.91, 0.13))

func _draw_grid() -> void:
	var grid_color := Color(0.17, 0.23, 0.29, 0.16)
	for x in range(0, int(size.x) + 1, 48):
		draw_line(Vector2(x, 0), Vector2(x, size.y), grid_color, 1)
	for y in range(0, int(size.y) + 1, 48):
		draw_line(Vector2(0, y), Vector2(size.x, y), grid_color, 1)

func _draw_title() -> void:
	var center := size * 0.5
	for radius in [230.0, 170.0, 112.0]:
		draw_arc(center, radius, -2.7, 2.4, 96, Color(0.39, 0.85, 0.91, 0.22), 3)
	draw_line(center - Vector2(280, 0), center - Vector2(70, 0), NPUIManager.ACCENT, 4)
	draw_line(center - Vector2(70, 0), center - Vector2(42, 90), NPUIManager.ACCENT, 4)
	draw_line(center - Vector2(42, 90), center + Vector2(12, 100), NPUIManager.TEXT, 5)
	draw_line(center + Vector2(12, 100), center + Vector2(55, 0), NPUIManager.TEXT, 5)
	draw_line(center + Vector2(55, 0), center + Vector2(280, 0), NPUIManager.ACCENT, 4)
	draw_circle(center + Vector2(55, 0), 10, NPUIManager.DANGER)

func _draw_medical() -> void:
	var floor_y := size.y * 0.78
	draw_rect(Rect2(size.x * 0.08, size.y * 0.18, size.x * 0.25, size.y * 0.48), Color("17232b"), true)
	draw_rect(Rect2(size.x * 0.67, size.y * 0.12, size.x * 0.20, size.y * 0.66), Color("121a22"), true)
	draw_rect(Rect2(size.x * 0.69, size.y * 0.18, size.x * 0.16, size.y * 0.54), Color("080b10"), true)
	draw_line(Vector2(0, floor_y), Vector2(size.x, floor_y), NPUIManager.BORDER, 4)
	var bed := Rect2(size.x * 0.25, size.y * 0.58, size.x * 0.38, size.y * 0.12)
	draw_rect(bed, Color("26343f"), true)
	draw_rect(bed, NPUIManager.ACCENT.darkened(0.35), false, 3)
	draw_line(Vector2(bed.position.x + 40, bed.end.y), Vector2(bed.position.x + 20, floor_y), NPUIManager.BORDER, 8)
	draw_line(Vector2(bed.end.x - 40, bed.end.y), Vector2(bed.end.x - 20, floor_y), NPUIManager.BORDER, 8)
	_draw_monitor(Vector2(size.x * 0.12, size.y * 0.25), Vector2(size.x * 0.17, size.y * 0.22), NPUIManager.SUCCESS)

func _draw_diagnostic() -> void:
	for i in range(4):
		var x := size.x * (0.08 + i * 0.22)
		_draw_monitor(Vector2(x, size.y * 0.18), Vector2(size.x * 0.16, size.y * 0.18), NPUIManager.DANGER if i == 2 else NPUIManager.ACCENT)
	draw_rect(Rect2(size.x * 0.15, size.y * 0.60, size.x * 0.70, size.y * 0.13), Color("17232b"), true)
	draw_line(Vector2(size.x * 0.5, size.y * 0.73), Vector2(size.x * 0.5, size.y), NPUIManager.BORDER, 6)
	for i in range(12):
		var x := size.x * 0.16 + i * size.x * 0.055
		var h := 18.0 + sin(i * 1.7) * 13.0
		draw_line(Vector2(x, size.y * 0.40 - h), Vector2(x, size.y * 0.40 + h), Color(0.39, 0.85, 0.91, 0.5), 3)

func _draw_security() -> void:
	var horizon := size.y * 0.28
	var center := Vector2(size.x * 0.5, size.y * 0.52)
	for x in [size.x * 0.08, size.x * 0.36, size.x * 0.66]:
		draw_rect(Rect2(x, horizon, size.x * 0.24, size.y * 0.48), Color("10161e"), true)
		draw_rect(Rect2(x, horizon, size.x * 0.24, size.y * 0.48), NPUIManager.BORDER, false, 4)
	draw_arc(center, size.x * 0.38, 3.35, 6.05, 80, Color(0.39, 0.85, 0.91, 0.24), 4)
	draw_circle(Vector2(size.x * 0.5, size.y * 0.78), 68, Color("0b1016"))
	draw_arc(Vector2(size.x * 0.5, size.y * 0.78), 68, 0, TAU, 64, NPUIManager.WARNING, 4)

func _draw_maintenance() -> void:
	for y_factor in [0.2, 0.72]:
		draw_line(Vector2(0, size.y * y_factor), Vector2(size.x, size.y * y_factor), Color("4d3f2c"), 24)
		draw_line(Vector2(0, size.y * y_factor), Vector2(size.x, size.y * y_factor), NPUIManager.WARNING.darkened(0.45), 4)
	for i in range(6):
		var x := size.x * (0.08 + i * 0.15)
		draw_rect(Rect2(x, size.y * 0.34, size.x * 0.09, size.y * 0.22), Color("181d22"), true)
		draw_rect(Rect2(x, size.y * 0.34, size.x * 0.09, size.y * 0.22), Color("6b5a3a"), false, 2)
	draw_circle(Vector2(size.x * 0.79, size.y * 0.45), 62, Color("0b0e12"))
	draw_arc(Vector2(size.x * 0.79, size.y * 0.45), 62, 0, TAU, 48, NPUIManager.WARNING, 5)

func _draw_quarantine() -> void:
	var glass := Rect2(size.x * 0.19, size.y * 0.12, size.x * 0.62, size.y * 0.66)
	draw_rect(glass, Color(0.20, 0.48, 0.53, 0.08), true)
	draw_rect(glass, NPUIManager.ACCENT.darkened(0.45), false, 5)
	for x in range(int(glass.position.x), int(glass.end.x), 72):
		draw_line(Vector2(x, glass.position.y), Vector2(x, glass.end.y), Color(0.39, 0.85, 0.91, 0.10), 1)
	var person := Vector2(size.x * 0.52, size.y * 0.48)
	draw_circle(person - Vector2(0, 65), 28, Color("7e8b93"))
	draw_line(person - Vector2(0, 35), person + Vector2(0, 75), Color("7e8b93"), 24)
	draw_line(person + Vector2(0, 8), person + Vector2(-55, 52), Color("7e8b93"), 13)
	draw_line(person + Vector2(0, 8), person + Vector2(55, 52), Color("7e8b93"), 13)
	draw_circle(Vector2(size.x * 0.72, size.y * 0.18), 12, NPUIManager.DANGER)

func _draw_archive() -> void:
	for i in range(5):
		var x := size.x * (0.06 + i * 0.19)
		var rack := Rect2(x, size.y * 0.10, size.x * 0.14, size.y * 0.68)
		draw_rect(rack, Color("10161e"), true)
		draw_rect(rack, NPUIManager.BORDER, false, 3)
		for row in range(8):
			var y := rack.position.y + 22 + row * rack.size.y / 9.0
			draw_line(Vector2(rack.position.x + 12, y), Vector2(rack.end.x - 12, y), Color("43515d"), 2)
			draw_circle(Vector2(rack.end.x - 23, y - 6), 3, NPUIManager.WARNING if row == i else NPUIManager.SUCCESS)

func _draw_uplink() -> void:
	var center := size * Vector2(0.5, 0.47)
	for radius in [235.0, 174.0, 112.0]:
		draw_arc(center, radius, 0, TAU, 96, Color(0.39, 0.85, 0.91, 0.20), 3)
	for i in range(18):
		var angle := TAU * float(i) / 18.0
		var point := center + Vector2(cos(angle), sin(angle)) * 235.0
		draw_circle(point, 6, NPUIManager.DANGER if i == 0 else NPUIManager.BORDER)
	var console_rect := Rect2(size.x * 0.28, size.y * 0.64, size.x * 0.44, size.y * 0.16)
	draw_rect(console_rect, Color("111821"), true)
	draw_rect(console_rect, NPUIManager.ACCENT.darkened(0.3), false, 4)
	for i in range(4):
		draw_circle(Vector2(console_rect.position.x + console_rect.size.x * (0.2 + i * 0.2), console_rect.position.y + console_rect.size.y * 0.5), 18, [NPUIManager.SUCCESS, NPUIManager.DANGER, NPUIManager.WARNING, NPUIManager.ACCENT][i])

func _draw_monitor(position: Vector2, monitor_size: Vector2, accent: Color) -> void:
	draw_rect(Rect2(position, monitor_size), Color("080b10"), true)
	draw_rect(Rect2(position, monitor_size), NPUIManager.BORDER, false, 3)
	var y := position.y + monitor_size.y * 0.52
	draw_line(Vector2(position.x + 14, y), Vector2(position.x + monitor_size.x * 0.30, y), accent, 3)
	draw_line(Vector2(position.x + monitor_size.x * 0.30, y), Vector2(position.x + monitor_size.x * 0.38, y - 22), accent, 3)
	draw_line(Vector2(position.x + monitor_size.x * 0.38, y - 22), Vector2(position.x + monitor_size.x * 0.46, y + 28), accent, 3)
	draw_line(Vector2(position.x + monitor_size.x * 0.46, y + 28), Vector2(position.x + monitor_size.x * 0.55, y), accent, 3)
	draw_line(Vector2(position.x + monitor_size.x * 0.55, y), Vector2(position.x + monitor_size.x - 14, y), accent, 3)

func _draw_vignette() -> void:
	var edge := Color(0, 0, 0, 0.30)
	draw_rect(Rect2(0, 0, size.x, 32), edge)
	draw_rect(Rect2(0, size.y - 32, size.x, 32), edge)
	draw_rect(Rect2(0, 0, 32, size.y), edge)
	draw_rect(Rect2(size.x - 32, 0, 32, size.y), edge)

