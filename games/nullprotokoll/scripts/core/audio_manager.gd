class_name NPAudioManager
extends Node

## Room ambience and one-shot effects.
##
## Every clip is optional: if an OGG is missing the call is a no-op, so the game
## still runs before SETUP_SPRACHE.ps1 or tools/generate_audio.py have been run.

const AMBIENCE_DIR := "res://assets/audio/ambience/"
const SFX_DIR := "res://assets/audio/sfx/"
const BUS_MUSIC := "Musik"
const BUS_EFFECTS := "Effekte"
const BUS_VOICE := "Stimme"
const CROSSFADE_SECONDS := 1.8
const SFX_VOICES := 6

var master_volume := 0.8
var music_volume := 0.55
var effects_volume := 0.75
var voice_volume := 0.9

var _ambience_players: Array[AudioStreamPlayer] = []
var _sfx_players: Array[AudioStreamPlayer] = []
var _active_ambience := 0
var _current_ambience_id := ""
var _fade_elapsed := 0.0
var _fade_active := false
var _stream_cache: Dictionary = {}
var _ready_for_playback := false


func _ready() -> void:
	_ensure_buses()
	for index in range(2):
		var player := AudioStreamPlayer.new()
		player.name = "Ambience%d" % index
		player.bus = BUS_MUSIC
		player.volume_db = -80.0
		add_child(player)
		_ambience_players.append(player)
	for index in range(SFX_VOICES):
		var player := AudioStreamPlayer.new()
		player.name = "Effect%d" % index
		player.bus = BUS_EFFECTS
		add_child(player)
		_sfx_players.append(player)
	_ready_for_playback = true
	set_process(true)
	_apply_bus_volumes()


func _ensure_buses() -> void:
	for bus_name in [BUS_MUSIC, BUS_EFFECTS, BUS_VOICE]:
		if AudioServer.get_bus_index(bus_name) >= 0:
			continue
		var index := AudioServer.bus_count
		AudioServer.add_bus(index)
		AudioServer.set_bus_name(index, bus_name)
		AudioServer.set_bus_send(index, "Master")


func apply_settings(settings: Dictionary) -> void:
	master_volume = float(settings.get("master_volume", 0.8))
	music_volume = float(settings.get("music_volume", 0.55))
	effects_volume = float(settings.get("effects_volume", 0.75))
	voice_volume = float(settings.get("voice_volume", 0.9))
	_apply_bus_volumes()


func _apply_bus_volumes() -> void:
	_set_bus_volume("Master", master_volume)
	_set_bus_volume(BUS_MUSIC, music_volume)
	_set_bus_volume(BUS_EFFECTS, effects_volume)
	_set_bus_volume(BUS_VOICE, voice_volume)


func _set_bus_volume(bus_name: String, linear: float) -> void:
	var index := AudioServer.get_bus_index(bus_name)
	if index < 0:
		return
	AudioServer.set_bus_mute(index, linear <= 0.001)
	AudioServer.set_bus_volume_db(index, linear_to_db(clampf(linear, 0.001, 1.0)))


func play_ambience(location_id: String) -> void:
	if not _ready_for_playback or location_id == _current_ambience_id:
		return
	var stream := _load_stream(AMBIENCE_DIR + location_id + ".ogg")
	_current_ambience_id = location_id
	if stream == null:
		_fade_out_all()
		return
	# GDScript verengt Typen nicht ueber "is": erst casten, dann Schleife setzen.
	var looping := stream as AudioStreamOggVorbis
	if looping != null:
		looping.loop = true
	var next_index := 1 - _active_ambience
	var next_player := _ambience_players[next_index]
	next_player.stream = stream
	next_player.volume_db = -80.0
	next_player.play()
	_active_ambience = next_index
	_fade_elapsed = 0.0
	_fade_active = true


func stop_ambience() -> void:
	_current_ambience_id = ""
	_fade_out_all()


func _fade_out_all() -> void:
	_fade_active = false
	for player in _ambience_players:
		player.stop()
		player.volume_db = -80.0


func _process(delta: float) -> void:
	if not _fade_active:
		return
	_fade_elapsed += delta
	var progress := clampf(_fade_elapsed / CROSSFADE_SECONDS, 0.0, 1.0)
	for index in range(_ambience_players.size()):
		var player := _ambience_players[index]
		var target := progress if index == _active_ambience else 1.0 - progress
		player.volume_db = linear_to_db(maxf(target, 0.0008))
		if target <= 0.001 and player.playing and progress >= 1.0:
			player.stop()
	if progress >= 1.0:
		_fade_active = false


func play_cue(cue_id: String) -> void:
	if not _ready_for_playback or cue_id.is_empty():
		return
	var stream := _load_stream(SFX_DIR + cue_id + ".ogg")
	if stream == null:
		return
	for player in _sfx_players:
		if player.playing:
			continue
		player.stream = stream
		player.pitch_scale = randf_range(0.96, 1.05)
		player.play()
		return
	# All voices busy: reuse the first one rather than dropping the cue.
	var fallback := _sfx_players[0]
	fallback.stream = stream
	fallback.play()


func cue_for_verb(verb: String) -> String:
	match verb.to_lower():
		"nehmen", "aufnehmen": return "item_pickup"
		"benutzen", "verwenden": return "device_use"
		"sprechen", "reden": return "comm_open"
		"gehen", "weiter": return "door_move"
		_: return "inspect"


func _load_stream(path: String) -> AudioStream:
	if _stream_cache.has(path):
		return _stream_cache[path]
	if not ResourceLoader.exists(path):
		_stream_cache[path] = null
		return null
	var resource := ResourceLoader.load(path)
	var stream := resource as AudioStream
	_stream_cache[path] = stream
	return stream
