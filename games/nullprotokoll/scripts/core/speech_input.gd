class_name NPSpeechInput
extends Node

## Microphone capture and local speech recognition.
##
## Audio never leaves the machine: the captured utterance is posted to a
## whisper.cpp server that SETUP_SPRACHE.ps1 installs and STARTEN.bat launches on
## 127.0.0.1. If that server is not running the node reports it once and the game
## continues on mouse and keyboard.

signal transcribed(text: String)
signal listening_changed(listening: bool)
signal status_changed(status: String, detail: String)

const RECORD_BUS := "Aufnahme"
const SERVER_URL := "http://127.0.0.1:8099/inference"
const TARGET_RATE := 16000
const MIN_SECONDS := 0.35
const MAX_SECONDS := 12.0
const BOUNDARY := "----NullprotokollVoiceBoundary"
const SILENCE_LEVEL := 0.012
const SILENCE_TAIL := 0.85

var enabled := true
var hands_free := false
var available := false

var _capture: AudioEffectCapture
var _microphone: AudioStreamPlayer
var _request: HTTPRequest
var _listening := false
var _busy := false
var _buffer := PackedFloat32Array()
var _mix_rate := 44100.0
var _silence_seconds := 0.0
var _voice_seen := false
var _server_warned := false


func _ready() -> void:
	_mix_rate = AudioServer.get_mix_rate()
	_request = HTTPRequest.new()
	_request.name = "SpeechRequest"
	_request.timeout = 25.0
	add_child(_request)
	_request.request_completed.connect(_on_request_completed)
	available = _prepare_capture()
	set_process(available)
	if not available:
		status_changed.emit("nicht_verfuegbar", "Mikrofon konnte nicht geöffnet werden.")


func _prepare_capture() -> bool:
	if DisplayServer.get_name() == "headless" or OS.has_feature("headless"):
		# Testläufe haben kein Audiogerät. Ohne diese Abkürzung würde der
		# Autoload beim Start jedes Testrunners ins Leere greifen.
		return false
	if not ProjectSettings.get_setting("audio/driver/enable_input", false):
		# The setting is baked into project.godot; without it Godot opens no
		# input device at all.
		push_warning("NPSpeechInput: audio/driver/enable_input ist deaktiviert.")
		return false
	var bus_index := AudioServer.get_bus_index(RECORD_BUS)
	if bus_index < 0:
		bus_index = AudioServer.bus_count
		AudioServer.add_bus(bus_index)
		AudioServer.set_bus_name(bus_index, RECORD_BUS)
		AudioServer.set_bus_send(bus_index, "Master")
	# The bus is silent on the way out; AudioEffectCapture taps it before the
	# output volume, so recording still works and nothing is echoed back.
	AudioServer.set_bus_volume_db(bus_index, -80.0)

	var has_capture := false
	for effect_index in range(AudioServer.get_bus_effect_count(bus_index)):
		var effect := AudioServer.get_bus_effect(bus_index, effect_index)
		if effect is AudioEffectCapture:
			_capture = effect
			has_capture = true
			break
	if not has_capture:
		_capture = AudioEffectCapture.new()
		_capture.buffer_length = 0.6
		AudioServer.add_bus_effect(bus_index, _capture)

	_microphone = AudioStreamPlayer.new()
	_microphone.name = "MicrophoneTap"
	_microphone.stream = AudioStreamMicrophone.new()
	_microphone.bus = RECORD_BUS
	_microphone.autoplay = false
	add_child(_microphone)
	_microphone.play()
	return _capture != null


func set_enabled(value: bool) -> void:
	enabled = value
	if not enabled and _listening:
		cancel()
	set_process(available and enabled)


func set_hands_free(value: bool) -> void:
	hands_free = value
	_silence_seconds = 0.0
	_voice_seen = false


func is_listening() -> bool:
	return _listening


func is_busy() -> bool:
	return _busy


func start_listening() -> void:
	if not available or not enabled or _busy or _listening:
		return
	_buffer = PackedFloat32Array()
	_silence_seconds = 0.0
	_voice_seen = false
	if _capture != null:
		_capture.clear_buffer()
	_listening = true
	listening_changed.emit(true)
	status_changed.emit("hoert_zu", "")


func stop_listening() -> void:
	if not _listening:
		return
	_listening = false
	listening_changed.emit(false)
	_drain_capture()
	var seconds := float(_buffer.size()) / _mix_rate
	if seconds < MIN_SECONDS or not _voice_seen:
		status_changed.emit("zu_kurz", "Nichts verstanden.")
		_buffer = PackedFloat32Array()
		return
	_send_for_recognition()


func cancel() -> void:
	_listening = false
	_buffer = PackedFloat32Array()
	listening_changed.emit(false)
	status_changed.emit("abgebrochen", "")


func _process(delta: float) -> void:
	if not available or not enabled:
		return
	if _listening:
		_drain_capture()
		if float(_buffer.size()) / _mix_rate >= MAX_SECONDS:
			stop_listening()
		elif hands_free and _voice_seen:
			if _silence_seconds >= SILENCE_TAIL:
				stop_listening()
		return
	if hands_free and not _busy:
		# Idle listening only starts once the microphone actually carries signal,
		# which keeps room noise from opening an endless recording.
		_drain_capture()
		if _voice_seen:
			var carried := _buffer
			start_listening()
			_buffer = carried
		else:
			_buffer = PackedFloat32Array()


func _drain_capture() -> void:
	if _capture == null:
		return
	var frames_available := _capture.get_frames_available()
	if frames_available <= 0:
		return
	var frames := _capture.get_buffer(frames_available)
	var loudest := 0.0
	for frame in frames:
		var mono := (frame.x + frame.y) * 0.5
		_buffer.append(mono)
		loudest = maxf(loudest, absf(mono))
	var chunk_seconds := float(frames.size()) / _mix_rate
	if loudest >= SILENCE_LEVEL:
		_voice_seen = true
		_silence_seconds = 0.0
	else:
		_silence_seconds += chunk_seconds
	# Cap the rolling buffer while idle so hands-free mode cannot grow forever.
	if not _listening:
		var maximum := int(_mix_rate * 0.8)
		if _buffer.size() > maximum:
			_buffer = _buffer.slice(_buffer.size() - maximum)


func _send_for_recognition() -> void:
	var wav := _build_wav(_resample(_buffer, _mix_rate, float(TARGET_RATE)))
	_buffer = PackedFloat32Array()
	_busy = true
	status_changed.emit("erkennt", "")
	var body := _multipart_body(wav)
	var headers := [
		"Content-Type: multipart/form-data; boundary=" + BOUNDARY,
		"Content-Length: %d" % body.size()
	]
	var error := _request.request_raw(SERVER_URL, headers, HTTPClient.METHOD_POST, body)
	if error != OK:
		_busy = false
		_warn_server_once("Spracherkennung nicht erreichbar (Fehler %d) – SPRACHE_EINRICHTEN.bat ausführen." % error)


func _on_request_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_busy = false
	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		_warn_server_once("Spracherkennung antwortet nicht – einmalig SPRACHE_EINRICHTEN.bat ausführen.")
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	var text := ""
	if parsed is Dictionary:
		text = str(parsed.get("text", ""))
	elif parsed is String:
		text = str(parsed)
	text = text.strip_edges()
	_server_warned = false
	if text.is_empty():
		status_changed.emit("leer", "Nichts verstanden.")
		return
	status_changed.emit("verstanden", text)
	transcribed.emit(text)


func _warn_server_once(message: String) -> void:
	if _server_warned:
		return
	_server_warned = true
	status_changed.emit("kein_dienst", message)


static func _resample(samples: PackedFloat32Array, source_rate: float, target_rate: float) -> PackedFloat32Array:
	if samples.is_empty() or source_rate <= 0.0 or absf(source_rate - target_rate) < 1.0:
		return samples
	var ratio := source_rate / target_rate
	var target_count := int(float(samples.size()) / ratio)
	var result := PackedFloat32Array()
	result.resize(target_count)
	for index in range(target_count):
		var source_position := float(index) * ratio
		var lower := int(floor(source_position))
		var upper := mini(lower + 1, samples.size() - 1)
		var blend := source_position - float(lower)
		result[index] = lerpf(samples[lower], samples[upper], blend)
	return result


static func _build_wav(samples: PackedFloat32Array) -> PackedByteArray:
	var data := PackedByteArray()
	var sample_count := samples.size()
	var byte_count := sample_count * 2
	data.append_array("RIFF".to_ascii_buffer())
	_append_uint32(data, 36 + byte_count)
	data.append_array("WAVEfmt ".to_ascii_buffer())
	_append_uint32(data, 16)
	_append_uint16(data, 1)
	_append_uint16(data, 1)
	_append_uint32(data, TARGET_RATE)
	_append_uint32(data, TARGET_RATE * 2)
	_append_uint16(data, 2)
	_append_uint16(data, 16)
	data.append_array("data".to_ascii_buffer())
	_append_uint32(data, byte_count)
	for index in range(sample_count):
		var value := int(clampf(samples[index], -1.0, 1.0) * 32767.0)
		_append_int16(data, value)
	return data


static func _append_uint32(data: PackedByteArray, value: int) -> void:
	data.append(value & 0xFF)
	data.append((value >> 8) & 0xFF)
	data.append((value >> 16) & 0xFF)
	data.append((value >> 24) & 0xFF)


static func _append_uint16(data: PackedByteArray, value: int) -> void:
	data.append(value & 0xFF)
	data.append((value >> 8) & 0xFF)


static func _append_int16(data: PackedByteArray, value: int) -> void:
	var unsigned := value if value >= 0 else value + 65536
	data.append(unsigned & 0xFF)
	data.append((unsigned >> 8) & 0xFF)


static func _multipart_body(wav: PackedByteArray) -> PackedByteArray:
	var body := PackedByteArray()
	body.append_array(("--" + BOUNDARY + "\r\n").to_utf8_buffer())
	body.append_array("Content-Disposition: form-data; name=\"file\"; filename=\"utterance.wav\"\r\n".to_utf8_buffer())
	body.append_array("Content-Type: audio/wav\r\n\r\n".to_utf8_buffer())
	body.append_array(wav)
	body.append_array("\r\n".to_utf8_buffer())
	for field in [["temperature", "0.0"], ["response_format", "json"], ["language", "de"]]:
		body.append_array(("--" + BOUNDARY + "\r\n").to_utf8_buffer())
		body.append_array(("Content-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % [field[0], field[1]]).to_utf8_buffer())
	body.append_array(("--" + BOUNDARY + "--\r\n").to_utf8_buffer())
	return body
