extends Node

func _ready() -> void:
	GameManager.save_manager.set_test_mode(true)
	var packed := load("res://scenes/main.tscn")
	var app = packed.instantiate()
	add_child(app)
	await _frames(4)
	_capture("menu")
	app.show_character_creation()
	await _frames(3)
	_capture("character")
	GameManager.new_game({"name": "Mira Vale", "presentation": "weiblich", "logic": 2, "empathy": 2, "instinct": 2}, 424242)
	app.show_game()
	await _frames(4)
	_capture("game")
	GameManager.state["world"]["current_location"] = "quarantaene"
	app.show_game()
	await _frames(4)
	_capture("game_quarantaene")
	GameManager.state["flags"].append("juna_free")
	GameManager.state["world"]["current_location"] = "relaiskern"
	app.show_game()
	await _frames(4)
	_capture("game_relaiskern")
	print("NULLPROTOKOLL – visuelle Testbilder erstellt")
	get_tree().quit(0)

func _frames(count: int) -> void:
	for _index in range(count):
		await get_tree().process_frame

func _capture(file_stem: String) -> void:
	var output_dir := ProjectSettings.globalize_path("res://tests/artifacts")
	DirAccess.make_dir_recursive_absolute(output_dir)
	var image := get_viewport().get_texture().get_image()
	var error := image.save_png(output_dir.path_join(file_stem + ".png"))
	if error != OK:
		printerr("Screenshot fehlgeschlagen: " + file_stem)
