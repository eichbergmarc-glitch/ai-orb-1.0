class_name NPSaveManager
extends RefCounted

const SAVE_PATH := "user://nullprotokoll_save.json"
const CHECKPOINT_PATH := "user://nullprotokoll_checkpoint.json"
const SETTINGS_PATH := "user://nullprotokoll_settings.json"
const TEST_SAVE_PATH := "user://nullprotokoll_test_save.json"
const TEST_CHECKPOINT_PATH := "user://nullprotokoll_test_checkpoint.json"
const TEST_SETTINGS_PATH := "user://nullprotokoll_test_settings.json"

var test_mode := false

func set_test_mode(enabled: bool) -> void:
	test_mode = enabled

func _save_path() -> String:
	return TEST_SAVE_PATH if test_mode else SAVE_PATH

func _checkpoint_path() -> String:
	return TEST_CHECKPOINT_PATH if test_mode else CHECKPOINT_PATH

func _settings_path() -> String:
	return TEST_SETTINGS_PATH if test_mode else SETTINGS_PATH

func has_save() -> bool:
	return FileAccess.file_exists(_save_path())

func save_game(payload: Dictionary) -> bool:
	var file := FileAccess.open(_save_path(), FileAccess.WRITE)
	if file == null:
		return false
	file.store_string(JSON.stringify(payload, "\t"))
	return true

func load_game() -> Dictionary:
	return _load_json(_save_path())

func save_checkpoint(payload: Dictionary) -> bool:
	var file := FileAccess.open(_checkpoint_path(), FileAccess.WRITE)
	if file == null:
		return false
	file.store_string(JSON.stringify(payload, "\t"))
	return true

func load_checkpoint() -> Dictionary:
	return _load_json(_checkpoint_path())

func save_settings(settings: Dictionary) -> bool:
	var file := FileAccess.open(_settings_path(), FileAccess.WRITE)
	if file == null:
		return false
	file.store_string(JSON.stringify(settings, "\t"))
	return true

func load_settings() -> Dictionary:
	return _load_json(_settings_path())

func _load_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var file := FileAccess.open(path, FileAccess.READ)
	var parsed = JSON.parse_string(file.get_as_text())
	return parsed if parsed is Dictionary else {}
