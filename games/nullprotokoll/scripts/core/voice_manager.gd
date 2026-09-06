class_name NPVoiceManager
extends Node

## Spoken thoughts, dialogue and system voice.
##
## Two sources are combined on purpose:
##   * Pre-rendered Piper clips for the protagonist's inner voice and for the
##     human characters. They are produced once by tools/render_voice.py and
##     looked up by a hash of the line, so editing a line simply re-renders it.
##   * The operating system's own speech synthesis for MIRA and the station
##     system, because a live synthetic voice is the right texture for them and
##     it also covers lines that contain runtime placeholders.
##
## Everything degrades quietly: without clips and without OS voices the game is
## silent but fully playable.

signal line_started(role: String, text: String)
signal line_finished(role: String)
signal queue_emptied
signal clips_missing

const INDEX_PATH := "res://assets/voice/index.json"
const VOICE_DIR := "res://assets/voice/"
const BUS_VOICE := "Stimme"
const TTS_GRACE_SECONDS := 0.45
const MAX_QUEUE := 12

const ROLE_THOUGHT_FEMALE := "gedanke_w"
const ROLE_THOUGHT_MALE := "gedanke_m"
const ROLE_MIRA := "mira"
const ROLE_SYSTEM := "system"
const ROLE_JUNA := "juna"
const ROLE_SAMIR := "samir"
const ROLE_RADIO := "funk"

const LIVE_ROLES := [ROLE_MIRA, ROLE_SYSTEM]

var enabled := true
var thoughts_enabled := true
var presentation := "weiblich"
## Fehlt eine vorgerenderte Zeile, bleibt die Figur standardmaessig still.
## Die Systemstimme als Ersatz einzuschieben klingt mitten in einer Szene
## schlechter als gar keine Stimme; wer sie trotzdem will, schaltet sie ein.
var system_fallback := false
var _missing_reported := false

var _index: Dictionary = {}
var _queue: Array[Dictionary] = []
var _current: Dictionary = {}
var _player: AudioStreamPlayer
var _tts_voice_by_role: Dictionary = {}
var _tts_available := false
var _tts_started_at := 0.0
var _speaking_live := false


func _ready() -> void:
	_player = AudioStreamPlayer.new()
	_player.name = "VoicePlayer"
	_player.bus = BUS_VOICE
	add_child(_player)
	_player.finished.connect(_on_clip_finished)
	_load_index()
	_prepare_tts()
	set_process(true)


func _load_index() -> void:
	if not FileAccess.file_exists(INDEX_PATH):
		return
	var file := FileAccess.open(INDEX_PATH, FileAccess.READ)
	if file == null:
		return
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if parsed is Dictionary:
		_index = parsed.get("lines", parsed)


func _prepare_tts() -> void:
	var voices := DisplayServer.tts_get_voices_for_language("de")
	if voices.is_empty():
		voices = DisplayServer.tts_get_voices_for_language("en")
	_tts_available = not voices.is_empty()
	if not _tts_available:
		return
	_tts_voice_by_role[ROLE_MIRA] = voices[0]
	_tts_voice_by_role[ROLE_SYSTEM] = voices[voices.size() - 1]


func has_live_voice() -> bool:
	return _tts_available


func set_presentation(value: String) -> void:
	presentation = value


func apply_settings(settings: Dictionary) -> void:
	enabled = bool(settings.get("voice_enabled", true))
	thoughts_enabled = bool(settings.get("voice_thoughts", true))
	system_fallback = bool(settings.get("voice_system_fallback", false))
	if not enabled:
		stop_all()


func has_rendered_clips() -> bool:
	return not _index.is_empty()


static func voice_key(text: String) -> String:
	## Must match tools/render_voice.py exactly.
	var normalized := text.strip_edges()
	while normalized.contains("  "):
		normalized = normalized.replace("  ", " ")
	normalized = normalized.replace("\n", " ").replace("\t", " ")
	while normalized.contains("  "):
		normalized = normalized.replace("  ", " ")
	return normalized.sha256_text().substr(0, 16)


func role_for_log_entry(speaker: String, kind: String) -> String:
	var normalized := speaker.strip_edges().to_lower()
	if normalized.contains("mira"):
		return ROLE_MIRA
	if normalized.contains("juna"):
		return ROLE_JUNA
	if normalized.contains("samir"):
		return ROLE_SAMIR
	if normalized.contains("funk"):
		return ROLE_RADIO
	if normalized == "system" or kind == "system" or kind == "heading":
		return ROLE_SYSTEM
	return _thought_role()


func _thought_role() -> String:
	var normalized := presentation.to_lower()
	if normalized in ["maennlich", "männlich", "male", "mann"]:
		return ROLE_THOUGHT_MALE
	return ROLE_THOUGHT_FEMALE


func is_thought_role(role: String) -> bool:
	return role == ROLE_THOUGHT_FEMALE or role == ROLE_THOUGHT_MALE


func speak(role: String, text: String) -> void:
	if not enabled:
		return
	var line := text.strip_edges()
	if line.is_empty():
		return
	if is_thought_role(role) and not thoughts_enabled:
		return
	if _queue.size() >= MAX_QUEUE:
		_queue.pop_front()
	_queue.append({"role": role, "text": line})
	if _current.is_empty():
		_advance_queue()


func speak_log_entry(entry: Dictionary) -> void:
	var kind := str(entry.get("kind", "action"))
	if kind == "choice":
		return
	var text := str(entry.get("text", ""))
	speak(role_for_log_entry(str(entry.get("speaker", "")), kind), text)


func skip_current() -> void:
	_stop_playback()
	_advance_queue()


func stop_all() -> void:
	_queue.clear()
	_stop_playback()
	_current = {}


func is_busy() -> bool:
	return not _current.is_empty()


func _stop_playback() -> void:
	if is_instance_valid(_player) and _player.playing:
		_player.stop()
	if _speaking_live:
		DisplayServer.tts_stop()
		_speaking_live = false
	if not _current.is_empty():
		line_finished.emit(str(_current.get("role", "")))
	_current = {}


func _advance_queue() -> void:
	if _queue.is_empty():
		_current = {}
		queue_emptied.emit()
		return
	_current = _queue.pop_front()
	var role := str(_current.get("role", ""))
	var text := str(_current.get("text", ""))
	line_started.emit(role, text)

	if not LIVE_ROLES.has(role):
		var stream := _clip_for(role, text)
		if stream != null:
			_player.stream = stream
			_player.play()
			return
		if not _missing_reported:
			_missing_reported = true
			clips_missing.emit()
		if not system_fallback:
			# Untertitel bleiben, Stimme schweigt.
			call_deferred("_finish_current")
			return
	_speak_live(role, text)


func _clip_for(role: String, text: String) -> AudioStream:
	var key := voice_key(text)
	var entry: Variant = _index.get(key, null)
	var file_name := ""
	if entry is Dictionary:
		var by_role: Dictionary = entry.get("roles", {})
		file_name = str(by_role.get(role, ""))
	elif entry is String:
		file_name = str(entry)
	if file_name.is_empty():
		file_name = "%s/%s.ogg" % [role, key]
	var path := VOICE_DIR + file_name
	if not ResourceLoader.exists(path):
		return null
	var resource := ResourceLoader.load(path)
	return resource as AudioStream


func _speak_live(role: String, text: String) -> void:
	if not _tts_available:
		# Nothing can speak this line; keep the queue moving.
		call_deferred("_finish_current")
		return
	var voice := str(_tts_voice_by_role.get(role, ""))
	if voice.is_empty():
		var voices := DisplayServer.tts_get_voices_for_language("de")
		voice = voices[0] if not voices.is_empty() else ""
	var pitch := 1.0
	var rate := 1.0
	match role:
		ROLE_MIRA:
			pitch = 0.92
			rate = 0.94
		ROLE_SYSTEM:
			pitch = 0.78
			rate = 1.08
	DisplayServer.tts_stop()
	DisplayServer.tts_speak(text, voice, 60, pitch, rate, 0, true)
	_speaking_live = true
	_tts_started_at = float(Time.get_ticks_msec()) / 1000.0


func _process(_delta: float) -> void:
	if not _speaking_live:
		return
	var elapsed := float(Time.get_ticks_msec()) / 1000.0 - _tts_started_at
	if elapsed < TTS_GRACE_SECONDS:
		return
	if not DisplayServer.tts_is_speaking():
		_speaking_live = false
		_finish_current()


func _on_clip_finished() -> void:
	_finish_current()


func _finish_current() -> void:
	if _current.is_empty():
		return
	line_finished.emit(str(_current.get("role", "")))
	_current = {}
	_advance_queue()
