class_name NPUIManager
extends RefCounted

const BG := Color("090c11")
const PANEL := Color("111821")
const PANEL_RAISED := Color("18222d")
const BORDER := Color("2b3948")
const TEXT := Color("eef3f7")
const MUTED := Color("a8b4bf")
const ACCENT := Color("64d8e8")
const WARNING := Color("f2b84b")
const DANGER := Color("f16b72")
const SUCCESS := Color("66d19e")

static func create_theme(settings: Dictionary) -> Theme:
	var result := Theme.new()
	var scale := float(settings.get("text_scale", 1.0))
	var contrast := bool(settings.get("high_contrast", false))
	var body_color := Color.WHITE if contrast else TEXT
	var panel_color := Color("05070a") if contrast else PANEL
	result.set_default_font_size(roundi(22.0 * scale))
	result.set_color("font_color", "Label", body_color)
	result.set_color("font_color", "Button", body_color)
	result.set_color("font_hover_color", "Button", Color.WHITE)
	result.set_color("font_pressed_color", "Button", Color.WHITE)
	result.set_color("font_disabled_color", "Button", MUTED.darkened(0.35))
	result.set_color("font_color", "RichTextLabel", body_color)
	result.set_color("default_color", "RichTextLabel", body_color)
	result.set_color("font_color", "LineEdit", body_color)
	result.set_color("font_placeholder_color", "LineEdit", MUTED)
	result.set_font_size("font_size", "Label", roundi(22.0 * scale))
	result.set_font_size("font_size", "Button", roundi(20.0 * scale))
	result.set_font_size("normal_font_size", "RichTextLabel", roundi(22.0 * scale))
	result.set_font_size("font_size", "LineEdit", roundi(22.0 * scale))
	result.set_stylebox("panel", "PanelContainer", panel_style(panel_color, BORDER, 12, 2))
	result.set_stylebox("normal", "Button", panel_style(PANEL_RAISED, BORDER, 8, 1))
	result.set_stylebox("hover", "Button", panel_style(PANEL_RAISED.lightened(0.09), ACCENT, 8, 2))
	result.set_stylebox("pressed", "Button", panel_style(PANEL_RAISED.darkened(0.08), ACCENT, 8, 2))
	result.set_stylebox("focus", "Button", panel_style(Color.TRANSPARENT, Color.WHITE, 8, 3))
	result.set_stylebox("disabled", "Button", panel_style(PANEL.darkened(0.15), BORDER.darkened(0.25), 8, 1))
	result.set_stylebox("normal", "LineEdit", panel_style(PANEL_RAISED, BORDER, 8, 1))
	result.set_stylebox("focus", "LineEdit", panel_style(PANEL_RAISED, ACCENT, 8, 2))
	result.set_stylebox("read_only", "LineEdit", panel_style(PANEL, BORDER, 8, 1))
	result.set_stylebox("normal", "ProgressBar", panel_style(PANEL, BORDER, 6, 1))
	result.set_stylebox("fill", "ProgressBar", panel_style(ACCENT, ACCENT, 6, 0))
	result.set_constant("separation", "VBoxContainer", 14)
	result.set_constant("separation", "HBoxContainer", 14)
	return result

static func panel_style(color: Color, border_color: Color, radius: int, width: int) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.border_color = border_color
	style.set_border_width_all(width)
	style.set_corner_radius_all(radius)
	style.content_margin_left = 22
	style.content_margin_right = 22
	style.content_margin_top = 18
	style.content_margin_bottom = 18
	return style

static func heading(label: Label, size: int, color := TEXT) -> Label:
	label.add_theme_font_size_override("font_size", size)
	label.add_theme_color_override("font_color", color)
	return label

static func muted(label: Label) -> Label:
	label.add_theme_color_override("font_color", MUTED)
	return label

static func accent_button(button: Button) -> Button:
	button.add_theme_stylebox_override("normal", panel_style(Color("12313a"), ACCENT, 8, 2))
	button.add_theme_stylebox_override("hover", panel_style(Color("17424d"), Color.WHITE, 8, 2))
	return button

static func danger_button(button: Button) -> Button:
	button.add_theme_stylebox_override("normal", panel_style(Color("351b22"), DANGER, 8, 2))
	button.add_theme_stylebox_override("hover", panel_style(Color("48232b"), Color.WHITE, 8, 2))
	return button

