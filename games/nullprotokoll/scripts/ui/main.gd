extends Control

var screen_root: Control
var modal_layer: Control
var current_screen := ""
var creation_profile := {"name": "Mira Vale", "presentation": "weiblich", "logic": 1, "empathy": 1, "instinct": 1}

var location_title_label: Label
var location_subtitle_label: Label
var time_label: Label
var save_status_label: Label
var backdrop: PointClickStage
var hotspot_grid: GridContainer
var exit_row: HFlowContainer
var narrative_log: RichTextLabel
var option_box: VBoxContainer
var selected_item_label: Label

var cutscenes: NPCutsceneLayer
var voice_status_label: Label
var voice_transcript_label: Label
var voice_toggle_button: Button

var spoken_log_count := 0
var played_cutscenes: Dictionary = {}
var last_spoken_line := ""

const FLAG_CUTSCENES := {
	"met_juna": "juna_erste_begegnung",
	"juna_free": "juna_befreit"
}

var pending_hotspot_id := ""
var pending_options: Array = []
var hotspot_mode := false
var selected_inventory_id := ""
var combine_first_id := ""
var modal_feedback := ""

func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	theme = NPUIManager.create_theme(GameManager.settings)
	GameManager.state_changed.connect(_on_state_changed)
	GameManager.save_completed.connect(_on_save_completed)
	GameManager.speech.transcribed.connect(_on_voice_command)
	GameManager.speech.listening_changed.connect(_on_listening_changed)
	GameManager.speech.status_changed.connect(_on_speech_status)
	GameManager.voice.line_started.connect(_on_voice_line_started)
	GameManager.voice.clips_missing.connect(_on_clips_missing)
	_ensure_cutscene_layer()
	show_main_menu()

func _unhandled_input(event: InputEvent) -> void:
	if not event is InputEventKey or event.echo:
		return
	var focused := get_viewport().gui_get_focus_owner()
	if focused is LineEdit:
		return

	# Sprechtaste zuerst: sie braucht Druck und Loslassen.
	if event.is_action("push_to_talk"):
		if event.pressed:
			_start_listening()
		else:
			_stop_listening()
		get_viewport().set_input_as_handled()
		return
	if not event.pressed:
		return

	if is_instance_valid(cutscenes) and cutscenes.is_playing():
		if event.is_action_pressed("ui_accept") or event.is_action_pressed("ui_cancel"):
			cutscenes.handle_key()
			get_viewport().set_input_as_handled()
		return
	if event.is_action_pressed("toggle_hands_free"):
		_toggle_hands_free()
		get_viewport().set_input_as_handled()
		return
	if event.is_action_pressed("repeat_line"):
		_repeat_last_line()
		get_viewport().set_input_as_handled()
		return

	if is_instance_valid(modal_layer):
		if event.is_action_pressed("ui_cancel"):
			_close_modal()
			get_viewport().set_input_as_handled()
		return
	if current_screen != "game":
		return
	if event.is_action_pressed("open_inventory"):
		_show_inventory()
		get_viewport().set_input_as_handled()
	elif event.is_action_pressed("open_journal"):
		_show_journal()
		get_viewport().set_input_as_handled()
	elif event.is_action_pressed("show_hotspots"):
		hotspot_mode = not hotspot_mode
		if is_instance_valid(backdrop):
			backdrop.set_hotspot_mode(hotspot_mode)
		get_viewport().set_input_as_handled()
	elif event.is_action_pressed("ui_cancel"):
		_show_pause()
		get_viewport().set_input_as_handled()

func show_main_menu() -> void:
	current_screen = "menu"
	pending_hotspot_id = ""
	pending_options.clear()
	_reset_screen()
	var title_backdrop := TextureRect.new()
	title_backdrop.texture = load("res://assets/backgrounds/relaiskern.png")
	title_backdrop.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	title_backdrop.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	title_backdrop.mouse_filter = Control.MOUSE_FILTER_IGNORE
	title_backdrop.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	screen_root.add_child(title_backdrop)
	var wash := ColorRect.new()
	wash.color = Color(0.02, 0.03, 0.045, 0.52)
	wash.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	wash.mouse_filter = Control.MOUSE_FILTER_IGNORE
	screen_root.add_child(wash)
	var margin := _full_margin(64)
	screen_root.add_child(margin)
	var layout := HBoxContainer.new()
	layout.add_theme_constant_override("separation", 64)
	margin.add_child(layout)
	var title_column := VBoxContainer.new()
	title_column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	layout.add_child(title_column)
	_add_spacer(title_column, true)
	var eyebrow := _make_label("ASTER-4 // VERBINDUNG GETRENNT", 20, NPUIManager.ACCENT)
	title_column.add_child(eyebrow)
	var title := _make_label("NULLPROTOKOLL", 64, NPUIManager.TEXT)
	title_column.add_child(title)
	var subtitle := _make_label("DAS ERWACHEN", 34, NPUIManager.MUTED)
	title_column.add_child(subtitle)
	var rule := HSeparator.new()
	rule.custom_minimum_size = Vector2(0, 28)
	title_column.add_child(rule)
	var premise := _make_label("Eine Stadt ohne Strom. Eine Stimme ohne Körper.\nDeine Zustimmung entscheidet, welche von beiden zurückkehrt.", 24, NPUIManager.TEXT)
	premise.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	premise.custom_minimum_size = Vector2(720, 100)
	title_column.add_child(premise)
	var duration := _make_label("STORY-ADVENTURE  ·  VERTICAL SLICE  ·  30–45 MINUTEN", 18, NPUIManager.MUTED)
	title_column.add_child(duration)
	_add_spacer(title_column, true)
	var menu_panel := PanelContainer.new()
	menu_panel.custom_minimum_size = Vector2(480, 650)
	layout.add_child(menu_panel)
	var menu_column := VBoxContainer.new()
	menu_column.add_theme_constant_override("separation", 18)
	menu_panel.add_child(menu_column)
	menu_column.add_child(_make_label("HAUPTMENÜ", 30, NPUIManager.TEXT))
	var continue_button := _make_button("Fortsetzen", _continue_game, true)
	continue_button.disabled = not GameManager.save_manager.has_save()
	continue_button.tooltip_text = "Kein lokaler Spielstand vorhanden." if continue_button.disabled else "Letzten automatischen Spielstand laden."
	menu_column.add_child(continue_button)
	menu_column.add_child(_make_button("Neues Spiel", show_character_creation, true))
	menu_column.add_child(_make_button("Spiel laden", _continue_game))
	menu_column.add_child(_make_button("Einstellungen", _show_settings))
	_add_spacer(menu_column, true)
	menu_column.add_child(_make_label("Tastatur: I Inventar · J Journal · H Hotspots · Esc Menü", 17, NPUIManager.MUTED))
	menu_column.add_child(_make_button("Beenden", _quit_game, false, true))
	var version := _make_label("PROLOG BUILD 0.1 · OFFLINE", 16, NPUIManager.MUTED)
	version.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	menu_column.add_child(version)
	continue_button.grab_focus()

func show_character_creation() -> void:
	current_screen = "character"
	_reset_screen()
	var background := ColorRect.new()
	background.color = NPUIManager.BG
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	screen_root.add_child(background)
	var margin := _full_margin(52)
	screen_root.add_child(margin)
	var root_column := VBoxContainer.new()
	root_column.add_theme_constant_override("separation", 24)
	margin.add_child(root_column)
	var top := HBoxContainer.new()
	root_column.add_child(top)
	top.add_child(_make_button("← Zurück", show_main_menu))
	var top_title := _make_label("WER WACHT AUF?", 38, NPUIManager.TEXT)
	top_title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	top.add_child(top_title)
	var placeholder := Control.new()
	placeholder.custom_minimum_size = Vector2(190, 1)
	top.add_child(placeholder)
	var body := HBoxContainer.new()
	body.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 28)
	root_column.add_child(body)
	var identity_panel := PanelContainer.new()
	identity_panel.custom_minimum_size = Vector2(760, 0)
	identity_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_child(identity_panel)
	var identity := VBoxContainer.new()
	identity_panel.add_child(identity)
	identity.add_child(_make_label("IDENTITÄT", 27, NPUIManager.ACCENT))
	identity.add_child(_make_label("Die Auswahl verändert Porträt, Name und Anrede – nicht deine Fähigkeiten.", 19, NPUIManager.MUTED))
	var cards := HBoxContainer.new()
	cards.add_theme_constant_override("separation", 18)
	identity.add_child(cards)
	cards.add_child(_character_choice_card("weiblich", "MIRA VALE\nweiblich", "res://assets/characters/protagonist_female.png"))
	cards.add_child(_character_choice_card("maennlich", "MAREK VALE\nmännlich", "res://assets/characters/protagonist_male.png"))
	identity.add_child(_make_label("Name", 19, NPUIManager.MUTED))
	var name_input := LineEdit.new()
	name_input.text = str(creation_profile["name"])
	name_input.max_length = 32
	name_input.placeholder_text = "Name des Charakters"
	name_input.custom_minimum_size = Vector2(0, 58)
	name_input.text_changed.connect(_on_name_changed)
	identity.add_child(name_input)
	var preview_text := "Sie wird in den Systemakten als Zeugenanker geführt." if creation_profile["presentation"] == "weiblich" else "Er wird in den Systemakten als Zeugenanker geführt."
	identity.add_child(_make_label(preview_text, 19, NPUIManager.MUTED))
	_add_spacer(identity, true)
	identity.add_child(_make_label("„Dein Name erscheint auf dem Terminal, bevor du weißt, ob er dir gehört.“", 23, NPUIManager.TEXT))
	var stats_panel := PanelContainer.new()
	stats_panel.custom_minimum_size = Vector2(760, 0)
	stats_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_child(stats_panel)
	var stats := VBoxContainer.new()
	stats_panel.add_child(stats)
	stats.add_child(_make_label("EIGENSCHAFTEN", 27, NPUIManager.ACCENT))
	var remaining := _remaining_points()
	var remaining_label := _make_label("NOCH %d PUNKTE" % remaining, 25, NPUIManager.WARNING if remaining > 0 else NPUIManager.SUCCESS)
	stats.add_child(remaining_label)
	stats.add_child(_stat_row("logic", "LOGIK", "Technische Systeme analysieren und Stromkreise überbrücken."))
	stats.add_child(_stat_row("empathy", "EMPATHIE", "Motive erkennen, Vertrauen gewinnen und Menschen erreichen."))
	stats.add_child(_stat_row("instinct", "INSTINKT", "Gefahren spüren, verborgene Fächer und riskante Wege finden."))
	_add_spacer(stats, true)
	var summary := _make_label("Jede Eigenschaft beginnt bei 1. Verteile alle drei zusätzlichen Punkte. Kein Weg macht den Prolog unlösbar.", 19, NPUIManager.MUTED)
	summary.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	stats.add_child(summary)
	var start := _make_button("Prolog beginnen", _begin_prologue, true)
	start.disabled = remaining != 0 or str(creation_profile["name"]).strip_edges().is_empty()
	start.custom_minimum_size = Vector2(0, 72)
	stats.add_child(start)

func _stat_row(key: String, title_text: String, description: String) -> Control:
	var panel := PanelContainer.new()
	panel.add_theme_stylebox_override("panel", NPUIManager.panel_style(NPUIManager.PANEL_RAISED, NPUIManager.BORDER, 9, 1))
	var column := VBoxContainer.new()
	panel.add_child(column)
	var row := HBoxContainer.new()
	column.add_child(row)
	var title := _make_label(title_text, 23, NPUIManager.TEXT)
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(title)
	var minus := _make_button("−", _adjust_stat.bind(key, -1))
	minus.custom_minimum_size = Vector2(56, 52)
	minus.disabled = int(creation_profile[key]) <= 1
	row.add_child(minus)
	var value := _make_label(str(creation_profile[key]), 28, NPUIManager.ACCENT)
	value.custom_minimum_size = Vector2(58, 52)
	value.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	value.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	row.add_child(value)
	var plus := _make_button("+", _adjust_stat.bind(key, 1))
	plus.custom_minimum_size = Vector2(56, 52)
	plus.disabled = _remaining_points() <= 0 or int(creation_profile[key]) >= 4
	row.add_child(plus)
	column.add_child(_make_label(description, 18, NPUIManager.MUTED))
	return panel

func _character_choice_card(presentation: String, label_text: String, texture_path: String) -> Control:
	var selected := str(creation_profile.get("presentation", "weiblich")) == presentation
	var card := VBoxContainer.new()
	card.custom_minimum_size = Vector2(300, 310)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var preview_panel := PanelContainer.new()
	preview_panel.custom_minimum_size = Vector2(0, 238)
	preview_panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	preview_panel.add_theme_stylebox_override("panel", NPUIManager.panel_style(Color("101922"), NPUIManager.ACCENT if selected else NPUIManager.BORDER, 8, 2 if selected else 1))
	card.add_child(preview_panel)
	var preview := TextureButton.new()
	preview.texture_normal = load(texture_path)
	preview.ignore_texture_size = true
	preview.stretch_mode = TextureButton.STRETCH_KEEP_ASPECT_CENTERED
	preview.tooltip_text = "Diesen Charakter wählen"
	preview.pressed.connect(_select_presentation.bind(presentation))
	preview_panel.add_child(preview)
	var choose := _make_button(label_text, _select_presentation.bind(presentation))
	choose.custom_minimum_size = Vector2(0, 62)
	if selected:
		NPUIManager.accent_button(choose)
	card.add_child(choose)
	return card

func show_game() -> void:
	if not GameManager.has_active_game():
		show_main_menu()
		return
	current_screen = "game"
	_reset_screen()
	var background := ColorRect.new()
	background.color = NPUIManager.BG
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	screen_root.add_child(background)
	var margin := _full_margin(30)
	screen_root.add_child(margin)
	var page := VBoxContainer.new()
	page.add_theme_constant_override("separation", 16)
	margin.add_child(page)
	var top_panel := PanelContainer.new()
	top_panel.custom_minimum_size = Vector2(0, 76)
	page.add_child(top_panel)
	var top := HBoxContainer.new()
	top_panel.add_child(top)
	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top.add_child(titles)
	location_title_label = _make_label("", 26, NPUIManager.TEXT)
	location_subtitle_label = _make_label("", 17, NPUIManager.MUTED)
	titles.add_child(location_title_label)
	titles.add_child(location_subtitle_label)
	time_label = _make_label("", 20, NPUIManager.WARNING)
	time_label.custom_minimum_size = Vector2(210, 0)
	top.add_child(time_label)
	save_status_label = _make_label("AUTOSAVE AKTIV", 16, NPUIManager.SUCCESS)
	save_status_label.custom_minimum_size = Vector2(160, 0)
	top.add_child(save_status_label)
	top.add_child(_make_button("Journal  [J]", _show_journal))
	top.add_child(_make_button("Inventar  [I]", _show_inventory))
	top.add_child(_make_button("Status", _show_character_status))
	top.add_child(_make_button("Menü  [Esc]", _show_pause))
	var split := HSplitContainer.new()
	split.size_flags_vertical = Control.SIZE_EXPAND_FILL
	split.split_offset = 1320
	page.add_child(split)
	var left := VBoxContainer.new()
	left.custom_minimum_size = Vector2(1140, 0)
	left.add_theme_constant_override("separation", 12)
	split.add_child(left)
	var scene_panel := PanelContainer.new()
	scene_panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scene_panel.custom_minimum_size = Vector2(0, 620)
	scene_panel.add_theme_stylebox_override("panel", NPUIManager.panel_style(Color("05090d"), NPUIManager.BORDER, 6, 1))
	left.add_child(scene_panel)
	backdrop = PointClickStage.new()
	backdrop.custom_minimum_size = Vector2(960, 540)
	backdrop.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	backdrop.size_flags_vertical = Control.SIZE_EXPAND_FILL
	backdrop.hotspot_reached.connect(_execute_hotspot)
	backdrop.exit_reached.connect(_execute_exit)
	scene_panel.add_child(backdrop)
	selected_item_label = _make_label("Kein Gegenstand ausgewählt", 18, NPUIManager.MUTED)
	left.add_child(selected_item_label)
	var controls := HBoxContainer.new()
	controls.add_theme_constant_override("separation", 12)
	left.add_child(controls)
	var mouse_help := _make_label("SPRICH ODER KLICKE  ·  T gedrückt halten und sprechen  ·  „geh zum Terminal“ · „öffne den Schrank“", 16, NPUIManager.MUTED)
	mouse_help.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	controls.add_child(mouse_help)
	controls.add_child(_make_button("Objekte zeigen  [H]", _toggle_hotspot_mode))
	controls.add_child(_make_button("Auswahl aufheben", _clear_world_item_selection))
	var voice_row := HBoxContainer.new()
	voice_row.add_theme_constant_override("separation", 12)
	left.add_child(voice_row)
	voice_status_label = _make_label("", 17, NPUIManager.MUTED)
	voice_status_label.custom_minimum_size = Vector2(330, 0)
	voice_row.add_child(voice_status_label)
	voice_transcript_label = _make_label("", 17, NPUIManager.ACCENT)
	voice_transcript_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	voice_transcript_label.clip_text = true
	voice_row.add_child(voice_transcript_label)
	voice_toggle_button = _make_button("Freihändig  [V]", _toggle_hands_free)
	voice_row.add_child(voice_toggle_button)
	_update_voice_hud()
	# Unsichtbare Fallback-Container halten die bisherige Tastatur-/Test-API intakt,
	# ohne die grafische Bühne mit einer zweiten Objektliste zu verkleinern.
	hotspot_grid = GridContainer.new()
	hotspot_grid.columns = 3
	hotspot_grid.visible = false
	left.add_child(hotspot_grid)
	exit_row = HFlowContainer.new()
	exit_row.visible = false
	left.add_child(exit_row)
	var story_panel := PanelContainer.new()
	story_panel.custom_minimum_size = Vector2(470, 0)
	split.add_child(story_panel)
	var story_column := VBoxContainer.new()
	story_panel.add_child(story_column)
	var story_header := HBoxContainer.new()
	story_column.add_child(story_header)
	var narrative_title := _make_label("PROTOKOLL", 23, NPUIManager.ACCENT)
	narrative_title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	story_header.add_child(narrative_title)
	story_header.add_child(_make_label("ENTSCHEIDUNGEN WERDEN GESPEICHERT", 15, NPUIManager.MUTED))
	narrative_log = RichTextLabel.new()
	narrative_log.bbcode_enabled = false
	narrative_log.selection_enabled = true
	narrative_log.scroll_active = true
	narrative_log.scroll_following = false
	narrative_log.size_flags_vertical = Control.SIZE_EXPAND_FILL
	narrative_log.custom_minimum_size = Vector2(0, 400)
	narrative_log.add_theme_constant_override("line_separation", 8)
	story_column.add_child(narrative_log)
	var decision_rule := HSeparator.new()
	story_column.add_child(decision_rule)
	var option_scroll := ScrollContainer.new()
	option_scroll.custom_minimum_size = Vector2(0, 230)
	option_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	story_column.add_child(option_scroll)
	option_box = VBoxContainer.new()
	option_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	option_scroll.add_child(option_box)
	_refresh_game()

func _refresh_game() -> void:
	if current_screen != "game" or not GameManager.has_active_game() or not is_instance_valid(location_title_label):
		return
	var location := GameManager.get_current_location()
	location_title_label.text = str(location.get("title", "Unbekannter Ort"))
	location_subtitle_label.text = str(location.get("subtitle", ""))
	var remaining := float(GameManager.state.get("world", {}).get("time_remaining", 72.0))
	var hours := int(floor(remaining))
	var minutes := int(floor((remaining - hours) * 60.0))
	time_label.text = "RESTZEIT  %02d:%02d" % [hours, minutes]
	var selected := GameManager.inventory.selected_item_id
	var selected_name := ""
	if selected.is_empty():
		selected_item_label.text = "Kein Gegenstand ausgewählt · Klicke in die Welt, um zu gehen · I: Inventar · H: Hotspot-Hinweise"
		selected_item_label.add_theme_color_override("font_color", NPUIManager.MUTED)
	else:
		selected_name = str(GameManager.inventory.get_item(selected).get("name", selected))
		selected_item_label.text = "BENUTZEN: %s · Klicke auf ein Objekt · Schaltfläche: Auswahl aufheben" % selected_name
		selected_item_label.add_theme_color_override("font_color", NPUIManager.ACCENT)
	backdrop.configure(
		location,
		GameManager.get_visible_hotspots(),
		GameManager.get_exits(),
		GameManager.state.get("completed_interactions", []),
		str(GameManager.state.get("player", {}).get("presentation", "weiblich")),
		GameManager.state.get("flags", [])
	)
	backdrop.set_hotspot_mode(hotspot_mode)
	backdrop.set_show_hotspot_labels(bool(GameManager.settings.get("show_hotspot_labels", true)))
	backdrop.set_reduce_motion(bool(GameManager.settings.get("reduce_motion", false)))
	backdrop.set_selected_item_label(selected_name)
	backdrop.set_input_locked(GameManager.dialogue.is_active() or not pending_hotspot_id.is_empty())
	if is_instance_valid(cutscenes):
		cutscenes.set_presentation(str(GameManager.state.get("player", {}).get("presentation", "weiblich")))
	_build_hotspots()
	_build_exits()
	_render_log()
	_render_options()
	_speak_new_log_entries()
	_check_flag_cutscenes()
	_update_voice_hud()

func _build_hotspots() -> void:
	if not is_instance_valid(hotspot_grid):
		return
	_clear_children(hotspot_grid)
	var hotspots := GameManager.get_visible_hotspots()
	var index := 1
	for hotspot in hotspots:
		var verb := str(hotspot.get("verb", "Ansehen")).to_upper()
		var prefix := "%d · " % index if hotspot_mode else ""
		var button := _make_button(prefix + verb + "\n" + str(hotspot.get("label", "Objekt")), _on_hotspot_pressed.bind(str(hotspot.get("id", ""))))
		button.custom_minimum_size = Vector2(300, 70)
		button.tooltip_text = "Ausgewählten Gegenstand hier benutzen" if not GameManager.inventory.selected_item_id.is_empty() else "Interagieren"
		if hotspot_mode:
			NPUIManager.accent_button(button)
		hotspot_grid.add_child(button)
		index += 1
	if not GameManager.inventory.selected_item_id.is_empty():
		var clear_button := _make_button("AUSWAHL AUFHEBEN", _clear_world_item_selection)
		clear_button.custom_minimum_size = Vector2(300, 70)
		hotspot_grid.add_child(clear_button)

func _build_exits() -> void:
	if not is_instance_valid(exit_row):
		return
	_clear_children(exit_row)
	exit_row.add_child(_make_label("WEGE", 17, NPUIManager.MUTED))
	for exit_data in GameManager.get_exits():
		var button := _make_button("→ " + str(exit_data.get("label", "Weiter")), _on_exit_pressed.bind(str(exit_data.get("id", ""))))
		button.custom_minimum_size = Vector2(245, 56)
		exit_row.add_child(button)

func _render_log() -> void:
	if not is_instance_valid(narrative_log):
		return
	narrative_log.clear()
	for entry in GameManager.state.get("log", []):
		var kind := str(entry.get("kind", "action"))
		var speaker := str(entry.get("speaker", ""))
		var color := NPUIManager.TEXT
		match kind:
			"heading": color = NPUIManager.ACCENT
			"system": color = NPUIManager.MUTED
			"location": color = NPUIManager.WARNING
			"dialogue": color = NPUIManager.ACCENT
			"player": color = NPUIManager.SUCCESS
			"choice": color = NPUIManager.SUCCESS
			"event": color = Color("b6a9d8")
		narrative_log.push_color(color)
		if kind == "heading":
			narrative_log.push_font_size(30)
			narrative_log.push_bold()
			narrative_log.add_text(str(entry.get("text", "")))
			narrative_log.pop()
			narrative_log.pop()
		else:
			if not speaker.is_empty():
				narrative_log.push_bold()
				narrative_log.add_text(speaker.to_upper() + "\n")
				narrative_log.pop()
			narrative_log.add_text(str(entry.get("text", "")))
		narrative_log.pop()
		narrative_log.add_text("\n\n")
	if bool(GameManager.settings.get("auto_scroll", true)):
		call_deferred("_scroll_log_to_bottom")

func _scroll_log_to_bottom() -> void:
	if is_instance_valid(narrative_log):
		narrative_log.scroll_to_line(maxi(0, narrative_log.get_line_count() - 1))

func _render_options() -> void:
	if not is_instance_valid(option_box):
		return
	_clear_children(option_box)
	var options: Array = []
	var dialogue_active := GameManager.dialogue.is_active()
	if dialogue_active:
		var view := GameManager.get_dialogue_view()
		options = view.get("options", [])
		option_box.add_child(_make_label("DEINE ANTWORT", 19, NPUIManager.ACCENT))
	elif not pending_hotspot_id.is_empty():
		options = pending_options
		option_box.add_child(_make_label("DEINE ENTSCHEIDUNG", 19, NPUIManager.WARNING))
	else:
		var hint := _make_label("Klicke direkt in der Szene auf ein Objekt oder einen Ausgang.\nEin Klick auf den Boden bewegt die Figur. Mit I öffnest du das Inventar; ein ausgewählter Gegenstand kann anschließend auf ein Objekt angewandt werden.", 18, NPUIManager.MUTED)
		hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		option_box.add_child(hint)
		return
	var number := 1
	for option in options:
		var button := _make_button("%d  %s" % [number, str(option.get("label", "Weiter"))], _on_dialogue_option.bind(str(option.get("id", ""))) if dialogue_active else _on_hotspot_option.bind(str(option.get("id", ""))))
		button.custom_minimum_size = Vector2(0, 64)
		button.alignment = HORIZONTAL_ALIGNMENT_LEFT
		button.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		option_box.add_child(button)
		number += 1
	if options.is_empty():
		option_box.add_child(_make_label("Dir fehlt noch eine passende Fähigkeit oder ein Gegenstand. Du kannst die Szene weiter untersuchen.", 18, NPUIManager.MUTED))

func _on_hotspot_pressed(hotspot_id: String) -> void:
	if is_instance_valid(backdrop) and backdrop.queue_hotspot(hotspot_id):
		return
	_execute_hotspot(hotspot_id)

func _execute_hotspot(hotspot_id: String) -> void:
	pending_hotspot_id = ""
	pending_options.clear()
	GameManager.audio_manager.play_cue(_cue_for_hotspot(hotspot_id))
	var result := GameManager.interact(hotspot_id)
	if result.has("choices"):
		pending_hotspot_id = hotspot_id
		pending_options = result.get("choices", [])
		if is_instance_valid(backdrop):
			backdrop.set_input_locked(true)
		_render_options()
	elif result.has("ending"):
		show_ending()
	else:
		_render_options()

func _on_hotspot_option(option_id: String) -> void:
	var context := pending_hotspot_id
	pending_hotspot_id = ""
	pending_options.clear()
	var result := GameManager.choose_interaction(context, option_id)
	if result.has("ending"):
		show_ending()
	else:
		_refresh_game()

func _on_dialogue_option(option_id: String) -> void:
	GameManager.choose_dialogue(option_id)
	_render_options()

func _on_exit_pressed(exit_id: String) -> void:
	if is_instance_valid(backdrop) and backdrop.queue_exit(exit_id):
		return
	_execute_exit(exit_id)

func _execute_exit(exit_id: String) -> void:
	pending_hotspot_id = ""
	pending_options.clear()
	GameManager.audio_manager.play_cue("door_move")
	GameManager.inventory.selected_item_id = ""
	GameManager.travel(exit_id)
	_refresh_game()

func _toggle_hotspot_mode() -> void:
	hotspot_mode = not hotspot_mode
	if is_instance_valid(backdrop):
		backdrop.set_hotspot_mode(hotspot_mode)

func _clear_world_item_selection() -> void:
	GameManager.inventory.selected_item_id = ""
	_refresh_game()

func _show_inventory() -> void:
	if not GameManager.has_active_game():
		return
	if selected_inventory_id.is_empty() and not GameManager.inventory.inventory.is_empty():
		selected_inventory_id = GameManager.inventory.inventory[0]
	var modal := _create_modal("INVENTAR", "Gegenstände untersuchen, kombinieren oder für die Spielwelt auswählen.")
	var body: VBoxContainer = modal["body"]
	var columns := HBoxContainer.new()
	columns.size_flags_vertical = Control.SIZE_EXPAND_FILL
	columns.add_theme_constant_override("separation", 24)
	body.add_child(columns)
	var list_panel := PanelContainer.new()
	list_panel.custom_minimum_size = Vector2(910, 620)
	list_panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	columns.add_child(list_panel)
	var scroll := ScrollContainer.new()
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	list_panel.add_child(scroll)
	var grid := GridContainer.new()
	grid.columns = 4
	grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(grid)
	for item in GameManager.inventory.get_all_items():
		var item_id := str(item.get("id", ""))
		var marker := "\n1. TEIL GEWÄHLT" if combine_first_id == item_id else ""
		var button := _make_button(str(item.get("name", item_id)) + "\n" + str(item.get("category", "")) + marker, _select_inventory_item.bind(item_id))
		button.custom_minimum_size = Vector2(205, 116)
		button.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		if selected_inventory_id == item_id or combine_first_id == item_id:
			NPUIManager.accent_button(button)
		grid.add_child(button)
	var detail_panel := PanelContainer.new()
	detail_panel.custom_minimum_size = Vector2(500, 620)
	columns.add_child(detail_panel)
	var detail := VBoxContainer.new()
	detail_panel.add_child(detail)
	var item_data := GameManager.inventory.get_item(selected_inventory_id)
	if item_data.is_empty():
		detail.add_child(_make_label("Das Inventar ist leer.", 22, NPUIManager.MUTED))
	else:
		detail.add_child(_make_label(str(item_data.get("name", "Gegenstand")), 28, NPUIManager.TEXT))
		detail.add_child(_make_label(str(item_data.get("category", "" )).to_upper(), 17, NPUIManager.ACCENT))
		var description := _make_label(str(item_data.get("description", "")), 21, NPUIManager.TEXT)
		description.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		detail.add_child(description)
		var hint := _make_label("HINWEIS\n" + str(item_data.get("hint", "Untersuche die Umgebung.")), 18, NPUIManager.MUTED)
		hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		detail.add_child(hint)
		_add_spacer(detail, true)
		if not modal_feedback.is_empty():
			var feedback := _make_label(modal_feedback, 18, NPUIManager.WARNING)
			feedback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
			detail.add_child(feedback)
		var use_button := _make_button("In der Spielwelt benutzen", _use_inventory_item, true)
		detail.add_child(use_button)
		var combine_text := "Mit diesem Gegenstand kombinieren" if combine_first_id.is_empty() else "Mit dem 1. Teil kombinieren"
		detail.add_child(_make_button(combine_text, _combine_inventory_item))
		if not combine_first_id.is_empty():
			detail.add_child(_make_button("Kombination abbrechen", _cancel_combine))

func _select_inventory_item(item_id: String) -> void:
	selected_inventory_id = item_id
	modal_feedback = ""
	_show_inventory()

func _use_inventory_item() -> void:
	if selected_inventory_id.is_empty():
		return
	GameManager.inventory.selected_item_id = selected_inventory_id
	combine_first_id = ""
	modal_feedback = ""
	_close_modal()
	_refresh_game()

func _combine_inventory_item() -> void:
	if selected_inventory_id.is_empty():
		return
	if combine_first_id.is_empty():
		combine_first_id = selected_inventory_id
		modal_feedback = "Erstes Teil gewählt. Wähle nun einen zweiten Gegenstand."
		_show_inventory()
		return
	if combine_first_id == selected_inventory_id:
		modal_feedback = "Wähle einen anderen Gegenstand als zweites Teil."
		_show_inventory()
		return
	var result := GameManager.combine_items(combine_first_id, selected_inventory_id)
	modal_feedback = str(result.get("text", ""))
	if bool(result.get("success", false)):
		selected_inventory_id = str(result.get("result", ""))
		combine_first_id = ""
	_show_inventory()

func _cancel_combine() -> void:
	combine_first_id = ""
	modal_feedback = "Kombinationsmodus beendet."
	_show_inventory()

func _show_journal() -> void:
	if not GameManager.has_active_game():
		return
	var modal := _create_modal("JOURNAL", "Nur Wissen, das du im aktuellen Spieldurchlauf entdeckt hast.")
	var body: VBoxContainer = modal["body"]
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	body.add_child(scroll)
	var entries := VBoxContainer.new()
	entries.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	entries.add_theme_constant_override("separation", 12)
	scroll.add_child(entries)
	for entry in GameManager.state.get("journal", []):
		var panel := PanelContainer.new()
		panel.add_theme_stylebox_override("panel", NPUIManager.panel_style(NPUIManager.PANEL_RAISED, NPUIManager.BORDER, 8, 1))
		entries.add_child(panel)
		var column := VBoxContainer.new()
		panel.add_child(column)
		var header := HBoxContainer.new()
		column.add_child(header)
		var category := _make_label(str(entry.get("category", "Eintrag")).to_upper(), 16, NPUIManager.ACCENT)
		category.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		header.add_child(category)
		header.add_child(_make_label(str(entry.get("status", "Bekannt")).to_upper(), 16, NPUIManager.WARNING))
		column.add_child(_make_label(str(entry.get("title", "Eintrag")), 24, NPUIManager.TEXT))
		var entry_text := _make_label(str(entry.get("text", "")), 19, NPUIManager.MUTED)
		entry_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		column.add_child(entry_text)

func _show_character_status() -> void:
	if not GameManager.has_active_game():
		return
	var modal := _create_modal("CHARAKTERSTATUS", "Fähigkeiten und sichtbare Beziehungen.")
	var body: VBoxContainer = modal["body"]
	var player: Dictionary = GameManager.state.get("player", {})
	body.add_child(_make_label(str(player.get("name", "")), 34, NPUIManager.TEXT))
	body.add_child(_make_label("LOGIK %d    EMPATHIE %d    INSTINKT %d" % [int(player.get("logic", 1)), int(player.get("empathy", 1)), int(player.get("instinct", 1))], 24, NPUIManager.ACCENT))
	body.add_child(HSeparator.new())
	body.add_child(_make_label("BEZIEHUNGEN", 22, NPUIManager.TEXT))
	var relations: Dictionary = GameManager.state.get("relationships", {})
	body.add_child(_relation_row("MIRA", int(relations.get("mira", 0))))
	body.add_child(_relation_row("Dr. Juna Falk", int(relations.get("juna", 0))))
	body.add_child(_relation_row("Samir Dastan", int(relations.get("samir", 0))))
	body.add_child(HSeparator.new())
	var solved_count := GameManager.puzzles.solved.size()
	body.add_child(_make_label("GELÖSTE VERBINDUNGEN  %d    ERINNERUNGSFRAGMENTE  %d" % [solved_count, int(GameManager.state.get("world", {}).get("memory_fragments", 0))], 20, NPUIManager.MUTED))
	var note := _make_label("Verborgene numerische Storywerte werden nicht angezeigt. Menschen reagieren auf das, was du getan und gesagt hast – nicht auf eine sichtbare Punktzahl.", 18, NPUIManager.MUTED)
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_child(note)

func _relation_row(person_name: String, value: int) -> Control:
	var row := HBoxContainer.new()
	var name_label := _make_label(person_name, 21, NPUIManager.TEXT)
	name_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(name_label)
	var status := "vertraut dir" if value >= 2 else ("ist dir zugeneigt" if value == 1 else ("bleibt vorsichtig" if value == 0 else ("misstraut dir" if value == -1 else "sieht dich als Gefahr")))
	row.add_child(_make_label(status, 20, NPUIManager.SUCCESS if value > 0 else (NPUIManager.DANGER if value < 0 else NPUIManager.MUTED)))
	return row

func _show_settings() -> void:
	var draft := GameManager.settings.duplicate(true)
	var modal := _create_modal("EINSTELLUNGEN", "Darstellung, Audio und Barrierefreiheit. Änderungen werden lokal gespeichert.")
	var body: VBoxContainer = modal["body"]
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	body.add_child(scroll)
	var settings_column := VBoxContainer.new()
	settings_column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	settings_column.add_theme_constant_override("separation", 16)
	scroll.add_child(settings_column)
	settings_column.add_child(_make_label("TEXT & BEDIENUNG", 21, NPUIManager.ACCENT))
	var scale_row := HBoxContainer.new()
	settings_column.add_child(scale_row)
	var scale_label := _make_label("Textgröße", 20, NPUIManager.TEXT)
	scale_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scale_row.add_child(scale_label)
	var scale_select := OptionButton.new()
	for entry in [["90 %", 0.9], ["100 %", 1.0], ["115 %", 1.15], ["130 %", 1.3]]:
		scale_select.add_item(entry[0])
		scale_select.set_item_metadata(scale_select.item_count - 1, entry[1])
		if is_equal_approx(float(draft.get("text_scale", 1.0)), float(entry[1])):
			scale_select.select(scale_select.item_count - 1)
	scale_select.item_selected.connect(func(index: int): draft["text_scale"] = scale_select.get_item_metadata(index))
	scale_row.add_child(scale_select)
	settings_column.add_child(_settings_toggle("Hoher Kontrast", "Verstärkt Panel- und Textkontraste.", "high_contrast", draft))
	settings_column.add_child(_settings_toggle("Bewegung reduzieren", "Deaktiviert Lauf-Bob und andere dekorative Bewegungen.", "reduce_motion", draft))
	settings_column.add_child(_settings_toggle("Hotspot-Bezeichnungen", "Zeigt beim Überfahren eines Objekts Aktion und Namen an.", "show_hotspot_labels", draft))
	settings_column.add_child(_settings_toggle("Protokoll automatisch scrollen", "Neue Ereignisse werden automatisch angezeigt.", "auto_scroll", draft))
	settings_column.add_child(_settings_toggle("Vollbild", "Wechselt zwischen Fenster und Vollbild.", "fullscreen", draft))
	settings_column.add_child(HSeparator.new())
	settings_column.add_child(_make_label("AUDIO", 21, NPUIManager.ACCENT))
	settings_column.add_child(_volume_row("Gesamtlautstärke", "master_volume", draft))
	settings_column.add_child(_volume_row("Musiklautstärke", "music_volume", draft))
	settings_column.add_child(_volume_row("Effektlautstärke", "effects_volume", draft))
	settings_column.add_child(_volume_row("Sprachlautstärke", "voice_volume", draft))
	settings_column.add_child(HSeparator.new())
	settings_column.add_child(_make_label("SPRACHE", 21, NPUIManager.ACCENT))
	settings_column.add_child(_settings_toggle("Stimmen hörbar", "Gedanken, Juna, Samir und MIRA werden gesprochen.", "voice_enabled", draft))
	settings_column.add_child(_settings_toggle("Gedanken hörbar", "Der innere Monolog der Spielfigur wird mitgesprochen.", "voice_thoughts", draft))
	settings_column.add_child(_settings_toggle("Ersatzstimme des Systems", "Springt ein, wenn eine Zeile noch nicht gerendert ist. Klingt deutlich synthetisch; standardmäßig bleibt die Figur dann still.", "voice_system_fallback", draft))
	settings_column.add_child(_settings_toggle("Sprachsteuerung", "Befehle über das Mikrofon. Maus und Tastatur bleiben aktiv.", "speech_enabled", draft))
	settings_column.add_child(_settings_toggle("Freihändig zuhören", "Ohne Sprechtaste. Sonst T gedrückt halten und sprechen.", "speech_hands_free", draft))
	var action_row := HBoxContainer.new()
	body.add_child(action_row)
	_add_spacer(action_row, false)
	action_row.add_child(_make_button("Abbrechen", _close_modal))
	action_row.add_child(_make_button("Übernehmen", _apply_settings.bind(draft), true))

func _settings_toggle(title_text: String, description: String, key: String, draft: Dictionary) -> Control:
	var row := HBoxContainer.new()
	var labels := VBoxContainer.new()
	labels.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	labels.add_child(_make_label(title_text, 20, NPUIManager.TEXT))
	labels.add_child(_make_label(description, 17, NPUIManager.MUTED))
	row.add_child(labels)
	var toggle := CheckButton.new()
	toggle.button_pressed = bool(draft.get(key, false))
	toggle.custom_minimum_size = Vector2(76, 48)
	toggle.toggled.connect(func(value: bool): draft[key] = value)
	row.add_child(toggle)
	return row

func _volume_row(title_text: String, key: String, draft: Dictionary) -> Control:
	var row := HBoxContainer.new()
	var label := _make_label(title_text, 20, NPUIManager.TEXT)
	label.custom_minimum_size = Vector2(290, 0)
	row.add_child(label)
	var slider := HSlider.new()
	slider.min_value = 0
	slider.max_value = 1
	slider.step = 0.05
	slider.value = float(draft.get(key, 0.8))
	slider.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	slider.custom_minimum_size = Vector2(500, 48)
	slider.value_changed.connect(func(value: float): draft[key] = value)
	row.add_child(slider)
	return row

func _apply_settings(draft: Dictionary) -> void:
	GameManager.update_settings(draft)
	theme = NPUIManager.create_theme(GameManager.settings)
	_close_modal()
	if current_screen == "game":
		show_game()
	elif current_screen == "menu":
		show_main_menu()
	elif current_screen == "character":
		show_character_creation()

func _show_pause() -> void:
	var modal := _create_modal("PAUSE", "Die Restzeit schreitet nur durch Handlungen fort.", Vector2(720, 720))
	var body: VBoxContainer = modal["body"]
	body.add_child(_make_button("Weiterspielen", _close_modal, true))
	body.add_child(_make_button("Jetzt speichern", _manual_save))
	var load_button := _make_button("Letzten Spielstand laden", _load_from_pause)
	load_button.disabled = not GameManager.save_manager.has_save()
	body.add_child(load_button)
	body.add_child(_make_button("Einstellungen", _show_settings))
	_add_spacer(body, true)
	body.add_child(_make_button("Zum Hauptmenü", _return_to_menu))
	body.add_child(_make_button("Spiel beenden", _quit_game, false, true))

func _manual_save() -> void:
	GameManager.save_game()
	modal_feedback = "Spielstand gespeichert."
	_close_modal()
	_refresh_game()

func _load_from_pause() -> void:
	_close_modal()
	if GameManager.load_game():
		show_game()

func show_ending() -> void:
	current_screen = "ending"
	_reset_screen()
	var ending := GameManager.get_ending_data()
	GameManager.audio_manager.play_cue("event_sting")
	_play_cutscene("ende_" + str(GameManager.state.get("ending", "")))
	var ending_backdrop := SceneBackdrop.new()
	ending_backdrop.set_scene({"id": "ending", "palette": "uplink", "title": "ENDE"}, bool(GameManager.settings.get("reduce_motion", false)))
	ending_backdrop.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	screen_root.add_child(ending_backdrop)
	var wash := ColorRect.new()
	wash.color = Color(0.01, 0.02, 0.03, 0.72)
	wash.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	screen_root.add_child(wash)
	var margin := _full_margin(64)
	screen_root.add_child(margin)
	var center := CenterContainer.new()
	margin.add_child(center)
	var panel := PanelContainer.new()
	panel.custom_minimum_size = Vector2(1320, 850)
	center.add_child(panel)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 18)
	panel.add_child(column)
	column.add_child(_make_label("PROLOG ABGESCHLOSSEN", 19, NPUIManager.ACCENT))
	column.add_child(_make_label(str(ending.get("title", "DEIN AUSGANG")), 43, NPUIManager.TEXT))
	column.add_child(_make_label(str(ending.get("tagline", "")), 25, NPUIManager.WARNING))
	var ending_text := _make_label(str(ending.get("text", "")), 23, NPUIManager.TEXT)
	ending_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(ending_text)
	column.add_child(HSeparator.new())
	column.add_child(_make_label("DEINE SPUREN", 20, NPUIManager.ACCENT))
	for consequence in ending.get("consequences", []):
		column.add_child(_make_label("• " + str(consequence), 20, NPUIManager.TEXT))
	for extra in _dynamic_ending_lines():
		column.add_child(_make_label("• " + extra, 20, NPUIManager.MUTED))
	_add_spacer(column, true)
	var buttons := HFlowContainer.new()
	buttons.add_theme_constant_override("h_separation", 12)
	buttons.add_theme_constant_override("v_separation", 12)
	column.add_child(buttons)
	var same_seed := _make_button("Mit gleichem Seed neu starten", _restart_same_seed)
	var new_seed := _make_button("Mit neuem Seed starten", _restart_new_seed, true)
	buttons.add_child(_make_button("Letzte Entscheidung laden", _load_last_decision))
	buttons.add_child(same_seed)
	buttons.add_child(new_seed)
	buttons.add_child(_make_button("Hauptmenü", show_main_menu))

func _dynamic_ending_lines() -> Array[String]:
	var lines: Array[String] = []
	var flags: Array = GameManager.state.get("flags", [])
	if flags.has("juna_free"):
		lines.append("Juna ist frei und kennt deine Entscheidung.")
	elif flags.has("juna_sedated"):
		lines.append("Juna blieb sediert in ASTER-4 zurück.")
	else:
		lines.append("Juna blieb hinter der Quarantänetür zurück.")
	if flags.has("secure_channel"):
		lines.append("Samirs gesicherter Kanal blieb unverfälscht.")
	if flags.has("audit_integrity_high"):
		lines.append("Alle drei Beweisketten des Audits sind intakt.")
	else:
		lines.append("Eine Beweiskette des Audits ging verloren.")
	if GameManager.state.get("secrets", []).has("west_null_erasure"):
		lines.append("Du kennst die Wahrheit über die gelöschten Menschen von WEST-NULL.")
	return lines

func _restart_same_seed() -> void:
	var profile: Dictionary = GameManager.state.get("player", {}).duplicate(true)
	var seed_value := int(GameManager.state.get("seed", 1))
	GameManager.new_game(profile, seed_value)
	show_game()

func _load_last_decision() -> void:
	if GameManager.load_checkpoint():
		show_game()

func _restart_new_seed() -> void:
	var profile: Dictionary = GameManager.state.get("player", {}).duplicate(true)
	GameManager.new_game(profile)
	show_game()

func _continue_game() -> void:
	if GameManager.load_game():
		if str(GameManager.state.get("ending", "")).is_empty():
			show_game()
		else:
			show_ending()

func _return_to_menu() -> void:
	GameManager.save_game()
	_close_modal()
	show_main_menu()

func _select_presentation(presentation: String) -> void:
	var old_default: bool = creation_profile["name"] == "Mira Vale" or creation_profile["name"] == "Marek Vale"
	creation_profile["presentation"] = presentation
	if old_default:
		creation_profile["name"] = "Mira Vale" if presentation == "weiblich" else "Marek Vale"
	show_character_creation()

func _on_name_changed(value: String) -> void:
	creation_profile["name"] = value

func _adjust_stat(key: String, delta: int) -> void:
	var value := int(creation_profile[key])
	if delta > 0 and (_remaining_points() <= 0 or value >= 4):
		return
	if delta < 0 and value <= 1:
		return
	creation_profile[key] = value + delta
	show_character_creation()

func _remaining_points() -> int:
	return 3 - ((int(creation_profile["logic"]) - 1) + (int(creation_profile["empathy"]) - 1) + (int(creation_profile["instinct"]) - 1))

func _begin_prologue() -> void:
	if _remaining_points() != 0 or str(creation_profile["name"]).strip_edges().is_empty():
		return
	if GameManager.new_game(creation_profile):
		spoken_log_count = 0
		played_cutscenes.clear()
		show_game()
		_play_cutscene("prolog_start")

func _on_state_changed() -> void:
	if current_screen == "game":
		_refresh_game()

func _on_save_completed(success: bool) -> void:
	if not is_instance_valid(save_status_label):
		return
	save_status_label.text = "GESPEICHERT" if success else "SPEICHERFEHLER"
	save_status_label.add_theme_color_override("font_color", NPUIManager.SUCCESS if success else NPUIManager.DANGER)

func _create_modal(title_text: String, subtitle_text: String, panel_size := Vector2(1580, 880)) -> Dictionary:
	_close_modal()
	if current_screen == "game" and is_instance_valid(backdrop):
		backdrop.set_input_locked(true)
	modal_layer = Control.new()
	modal_layer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	modal_layer.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(modal_layer)
	var dim := ColorRect.new()
	dim.color = Color(0.0, 0.0, 0.0, 0.78)
	dim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	dim.mouse_filter = Control.MOUSE_FILTER_STOP
	modal_layer.add_child(dim)
	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	modal_layer.add_child(center)
	var panel := PanelContainer.new()
	panel.custom_minimum_size = panel_size
	center.add_child(panel)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 16)
	panel.add_child(column)
	var header := HBoxContainer.new()
	column.add_child(header)
	var titles := VBoxContainer.new()
	titles.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	header.add_child(titles)
	titles.add_child(_make_label(title_text, 32, NPUIManager.TEXT))
	titles.add_child(_make_label(subtitle_text, 18, NPUIManager.MUTED))
	var close_button := _make_button("Schließen  [Esc]", _close_modal)
	header.add_child(close_button)
	column.add_child(HSeparator.new())
	var body := VBoxContainer.new()
	body.size_flags_vertical = Control.SIZE_EXPAND_FILL
	column.add_child(body)
	close_button.grab_focus()
	return {"layer": modal_layer, "body": body}

func _close_modal() -> void:
	if is_instance_valid(modal_layer):
		var parent := modal_layer.get_parent()
		if parent != null:
			parent.remove_child(modal_layer)
		modal_layer.queue_free()
	modal_layer = null
	if current_screen == "game" and is_instance_valid(backdrop):
		backdrop.set_input_locked(GameManager.dialogue.is_active() or not pending_hotspot_id.is_empty())

func _reset_screen() -> void:
	_close_modal()
	if is_instance_valid(screen_root):
		remove_child(screen_root)
		screen_root.queue_free()
	screen_root = Control.new()
	screen_root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(screen_root)

func _full_margin(amount: int) -> MarginContainer:
	var margin := MarginContainer.new()
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	margin.add_theme_constant_override("margin_left", amount)
	margin.add_theme_constant_override("margin_right", amount)
	margin.add_theme_constant_override("margin_top", amount)
	margin.add_theme_constant_override("margin_bottom", amount)
	return margin

func _make_label(text_value: String, size := 0, color := NPUIManager.TEXT) -> Label:
	var label := Label.new()
	label.text = text_value
	if size > 0:
		label.add_theme_font_size_override("font_size", size)
	label.add_theme_color_override("font_color", color)
	return label

func _make_button(text_value: String, callback: Callable, accent := false, danger := false) -> Button:
	var button := Button.new()
	button.text = text_value
	button.custom_minimum_size = Vector2(180, 56)
	button.focus_mode = Control.FOCUS_ALL
	button.pressed.connect(callback)
	if accent:
		NPUIManager.accent_button(button)
	if danger:
		NPUIManager.danger_button(button)
	return button

func _add_spacer(parent: Container, vertical: bool) -> void:
	var spacer := Control.new()
	if vertical:
		spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	else:
		spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	parent.add_child(spacer)

func _clear_children(parent: Node) -> void:
	for child in parent.get_children():
		parent.remove_child(child)
		child.queue_free()

func _quit_game() -> void:
	if GameManager.has_active_game():
		GameManager.save_game()
	get_tree().quit()


# ------------------------------------------------------------------ Sprache


func _ensure_cutscene_layer() -> void:
	if is_instance_valid(cutscenes):
		return
	cutscenes = NPCutsceneLayer.new()
	cutscenes.name = "Cutscenes"
	add_child(cutscenes)
	cutscenes.finished.connect(_on_cutscene_finished)
	cutscenes.beat_started.connect(_on_cutscene_beat)


func _play_cutscene(trigger_id: String) -> bool:
	_ensure_cutscene_layer()
	if trigger_id.is_empty() or played_cutscenes.has(trigger_id):
		return false
	if not cutscenes.has_sequence(trigger_id):
		return false
	played_cutscenes[trigger_id] = true
	cutscenes.set_presentation(str(GameManager.state.get("player", {}).get("presentation", "weiblich")))
	# Immer als oberste Ebene, auch nachdem der Bildschirm neu aufgebaut wurde.
	move_child(cutscenes, get_child_count() - 1)
	if is_instance_valid(backdrop):
		backdrop.set_input_locked(true)
	return cutscenes.play(trigger_id)


func _check_flag_cutscenes() -> void:
	var flags: Array = GameManager.state.get("flags", [])
	for flag_key in FLAG_CUTSCENES:
		if flags.has(flag_key):
			_play_cutscene(str(FLAG_CUTSCENES[flag_key]))


func _on_cutscene_beat(beat: Dictionary) -> void:
	var speaker := str(beat.get("speaker", ""))
	GameManager.voice.stop_all()
	GameManager.voice.speak(GameManager.voice.role_for_log_entry(speaker, "dialogue"), str(beat.get("text", "")))


func _on_cutscene_finished(_trigger_id: String) -> void:
	if is_instance_valid(backdrop):
		backdrop.set_input_locked(GameManager.dialogue.is_active() or not pending_hotspot_id.is_empty())


func _speak_new_log_entries() -> void:
	var entries: Array = GameManager.state.get("log", [])
	if entries.size() < spoken_log_count:
		# Nach dem Laden eines Spielstands wird nicht nachträglich vorgelesen.
		spoken_log_count = entries.size()
		return
	for index in range(spoken_log_count, entries.size()):
		var entry: Variant = entries[index]
		if entry is Dictionary:
			GameManager.voice.speak_log_entry(entry)
	spoken_log_count = entries.size()


func _on_voice_line_started(_role: String, text: String) -> void:
	last_spoken_line = text


func _on_clips_missing() -> void:
	## Einmalig, damit klar ist, warum Figuren stumm bleiben.
	if not is_instance_valid(voice_transcript_label):
		return
	voice_transcript_label.text = "Stimmen noch nicht gerendert – führe SETUP_STIMMEN.ps1 aus."
	voice_transcript_label.add_theme_color_override("font_color", NPUIManager.WARNING)


func _repeat_last_line() -> void:
	if last_spoken_line.is_empty():
		return
	GameManager.voice.stop_all()
	GameManager.voice.speak(GameManager.voice.role_for_log_entry("", "action"), last_spoken_line)


func _start_listening() -> void:
	if not GameManager.speech.available or not bool(GameManager.settings.get("speech_enabled", true)):
		return
	GameManager.audio_manager.play_cue("voice_listen_start")
	GameManager.speech.start_listening()


func _stop_listening() -> void:
	if GameManager.speech.is_listening():
		GameManager.audio_manager.play_cue("voice_listen_stop")
	GameManager.speech.stop_listening()


func _toggle_hands_free() -> void:
	var draft := GameManager.settings.duplicate(true)
	draft["speech_hands_free"] = not bool(draft.get("speech_hands_free", false))
	GameManager.update_settings(draft)
	_update_voice_hud()


func _on_listening_changed(_listening: bool) -> void:
	_update_voice_hud()


func _on_speech_status(status: String, detail: String) -> void:
	if not is_instance_valid(voice_transcript_label):
		return
	match status:
		"verstanden":
			voice_transcript_label.text = "„%s“" % detail
			voice_transcript_label.add_theme_color_override("font_color", NPUIManager.ACCENT)
		"kein_dienst", "nicht_verfuegbar":
			voice_transcript_label.text = detail
			voice_transcript_label.add_theme_color_override("font_color", NPUIManager.WARNING)
		"zu_kurz", "leer":
			voice_transcript_label.text = detail
			voice_transcript_label.add_theme_color_override("font_color", NPUIManager.MUTED)
			GameManager.audio_manager.play_cue("voice_fail")
		_:
			pass
	_update_voice_hud()


func _update_voice_hud() -> void:
	if not is_instance_valid(voice_status_label):
		return
	var speech := GameManager.speech
	var text := ""
	var color := NPUIManager.MUTED
	if not bool(GameManager.settings.get("speech_enabled", true)):
		text = "SPRACHSTEUERUNG AUS"
	elif not speech.available:
		text = "KEIN MIKROFON"
		color = NPUIManager.WARNING
	elif speech.is_listening():
		text = "◉ HÖRT ZU …"
		color = NPUIManager.DANGER
	elif speech.is_busy():
		text = "VERARBEITE …"
		color = NPUIManager.WARNING
	elif bool(GameManager.settings.get("speech_hands_free", false)):
		text = "FREIHÄNDIG BEREIT"
		color = NPUIManager.SUCCESS
	else:
		text = "T HALTEN UND SPRECHEN"
	voice_status_label.text = text
	voice_status_label.add_theme_color_override("font_color", color)
	if is_instance_valid(voice_toggle_button):
		var hands_free := bool(GameManager.settings.get("speech_hands_free", false))
		voice_toggle_button.text = "Freihändig: an  [V]" if hands_free else "Freihändig: aus  [V]"


func _voice_context() -> Dictionary:
	var hotspots: Array = []
	for hotspot in GameManager.get_visible_hotspots():
		hotspots.append({
			"id": str(hotspot.get("id", "")),
			"label": str(hotspot.get("label", "")),
			"verb": str(hotspot.get("verb", ""))
		})
	var exits: Array = []
	for exit_data in GameManager.get_exits():
		exits.append({
			"id": str(exit_data.get("id", "")),
			"label": str(exit_data.get("label", "")),
			"verb": str(exit_data.get("verb", ""))
		})
	var items: Array = []
	for item in GameManager.inventory.get_all_items():
		items.append({"id": str(item.get("id", "")), "name": str(item.get("name", ""))})
	var options: Array = []
	if GameManager.dialogue.is_active():
		for option in GameManager.get_dialogue_view().get("options", []):
			options.append({"id": str(option.get("id", "")), "label": str(option.get("label", ""))})
	elif not pending_hotspot_id.is_empty():
		for option in pending_options:
			options.append({"id": str(option.get("id", "")), "label": str(option.get("label", ""))})
	return {"hotspots": hotspots, "exits": exits, "items": items, "options": options}


func _on_voice_command(text: String) -> void:
	var command := NPCommandParser.parse(text, _voice_context())
	_dispatch_command(command)


func _dispatch_command(command: Dictionary) -> void:
	var intent := str(command.get("intent", "unknown"))

	if is_instance_valid(cutscenes) and cutscenes.is_playing():
		cutscenes.advance()
		return

	match intent:
		"choose":
			var option_id := str(command.get("target", ""))
			if GameManager.dialogue.is_active():
				_on_dialogue_option(option_id)
			elif not pending_hotspot_id.is_empty():
				_on_hotspot_option(option_id)
			return
		"move":
			if str(command.get("target_kind", "")) == "exit":
				_on_exit_pressed(str(command.get("target", "")))
			else:
				_approach_only(str(command.get("target", "")))
			return
		"move_direction":
			_step_direction(str(command.get("direction", "")))
			return
		"interact":
			if str(command.get("target_kind", "")) == "exit":
				_on_exit_pressed(str(command.get("target", "")))
			else:
				_on_hotspot_pressed(str(command.get("target", "")))
			return
		"select_item":
			_select_inventory_item(str(command.get("item", "")))
			_refresh_game()
			return
		"use_item":
			GameManager.inventory.selected_item_id = str(command.get("item", ""))
			_on_hotspot_pressed(str(command.get("target", "")))
			return
		"combine":
			var result := GameManager.combine_items(str(command.get("item", "")), str(command.get("secondary", "")))
			if not result.get("success", false):
				GameManager.audio_manager.play_cue("voice_fail")
			_refresh_game()
			return
		"inventory":
			_show_inventory()
			return
		"journal":
			_show_journal()
			return
		"status":
			_show_character_status()
			return
		"menu":
			_show_pause()
			return
		"close":
			_close_modal()
			return
		"save":
			_manual_save()
			return
		"hints":
			_toggle_hotspot_mode()
			return
		"repeat":
			_repeat_last_line()
			return
		"stop_voice":
			GameManager.voice.stop_all()
			return
		"look_around":
			_describe_room()
			return
		"help":
			_show_voice_help()
			return
		_:
			GameManager.audio_manager.play_cue("voice_fail")
			if is_instance_valid(voice_transcript_label):
				voice_transcript_label.text = "Nicht verstanden: „%s“" % str(command.get("transcript", ""))
				voice_transcript_label.add_theme_color_override("font_color", NPUIManager.WARNING)


func _approach_only(hotspot_id: String) -> void:
	if not is_instance_valid(backdrop):
		return
	var target := backdrop.get_approach_point("hotspot", hotspot_id)
	if target == Vector2.INF:
		return
	backdrop.walk_to(target)


func _step_direction(direction: String) -> void:
	if not is_instance_valid(backdrop):
		return
	var current := backdrop.get_player_position()
	var step := 260.0
	match direction:
		"links": current.x -= step
		"rechts": current.x += step
		"vor": current.y += step * 0.45
		"zurueck": current.y -= step * 0.45
	backdrop.walk_to(current)


func _describe_room() -> void:
	var location := GameManager.get_current_location()
	var names: Array[String] = []
	for hotspot in GameManager.get_visible_hotspots():
		names.append(str(hotspot.get("label", "")))
	var exits: Array[String] = []
	for exit_data in GameManager.get_exits():
		exits.append(str(exit_data.get("label", "")))
	var sentence := "%s. Du siehst: %s." % [str(location.get("title", "")), ", ".join(names)]
	if not exits.is_empty():
		sentence += " Wege: %s." % ", ".join(exits)
	GameManager.voice.stop_all()
	GameManager.voice.speak(GameManager.voice.role_for_log_entry("system", "system"), sentence)
	if is_instance_valid(voice_transcript_label):
		voice_transcript_label.text = sentence


func _show_voice_help() -> void:
	var modal := _create_modal("SPRACHBEFEHLE", "Halte T gedrückt und sprich. Mit V schaltest du auf freihändiges Zuhören um.")
	var body: VBoxContainer = modal["body"]
	var examples := [
		["Bewegen", "„bewege dich zum Tisch“ · „geh zur Tür“ · „nach links“"],
		["Handeln", "„öffne die Schublade“ · „nimm die Ampulle“ · „untersuche das Terminal“"],
		["Reden", "„rede mit Juna“ · „antwort zwei“ · „wähle die erste“"],
		["Gegenstände", "„benutze den Schlüssel am Schloss“ · „kombiniere Folie mit Draht“"],
		["Übersicht", "„inventar“ · „journal“ · „status“ · „zeige objekte“"],
		["Sonstiges", "„sieh dich um“ · „wiederhole“ · „sei still“ · „speichern“"]
	]
	for entry in examples:
		var row := VBoxContainer.new()
		row.add_theme_constant_override("separation", 2)
		row.add_child(_make_label(str(entry[0]).to_upper(), 19, NPUIManager.ACCENT))
		var line := _make_label(str(entry[1]), 20, NPUIManager.TEXT)
		line.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		row.add_child(line)
		body.add_child(row)
	_add_spacer(body, true)
	body.add_child(_make_button("Verstanden", _close_modal, true))


func _cue_for_hotspot(hotspot_id: String) -> String:
	for hotspot in GameManager.get_visible_hotspots():
		if str(hotspot.get("id", "")) == hotspot_id:
			return GameManager.audio_manager.cue_for_verb(str(hotspot.get("verb", "")))
	return "inspect"
