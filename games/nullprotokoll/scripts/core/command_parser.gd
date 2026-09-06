class_name NPCommandParser
extends RefCounted

## Turns a freely spoken German sentence into a game action.
##
## Whisper returns unconstrained text, so the parser works in three steps:
## normalise the sentence, decide the intent from its verb, then resolve the
## remaining words against the objects that are actually reachable right now.
## Everything here is pure data in, data out, which keeps it testable without a
## microphone and without the rest of the game.

const ACCEPT_THRESHOLD := 0.52
const STRONG_THRESHOLD := 0.78

const NUMBER_WORDS := {
	"null": 0, "eins": 1, "eine": 1, "einen": 1, "erste": 1, "ersten": 1, "erstes": 1,
	"zwei": 2, "zweite": 2, "zweiten": 2, "zweites": 2,
	"drei": 3, "dritte": 3, "dritten": 3, "drittes": 3,
	"vier": 4, "vierte": 4, "vierten": 4, "viertes": 4,
	"fuenf": 5, "fünf": 5, "fuenfte": 5, "fünfte": 5, "fuenften": 5, "fünften": 5,
	"sechs": 6, "sechste": 6, "sechsten": 6,
	"sieben": 7, "siebte": 7, "siebten": 7,
	"acht": 8, "achte": 8, "achten": 8,
	"neun": 9, "neunte": 9, "neunten": 9,
	"zehn": 10, "zehnte": 10, "zehnten": 10
}

const FILLER_WORDS := [
	"bitte", "mal", "doch", "jetzt", "sofort", "dann", "hier", "da", "dort",
	"dich", "dir", "mich", "mir", "ich", "du", "wir", "es", "der", "die", "das",
	"den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "zum", "zur",
	"zu", "nach", "in", "ins", "im", "an", "am", "auf", "aufs", "bei", "beim",
	"und", "mit", "vom", "von", "fuer", "für", "ueber", "über", "nochmal", "noch",
	"kannst", "kann", "wuerdest", "würdest", "wuerde", "würde", "soll", "sollst",
	"lass", "uns", "einfach", "gerne", "gern"
]

# Ordered by specificity: the first phrase that matches wins.
const INTENT_PATTERNS := [
	{"intent": "combine", "phrases": ["kombiniere", "kombinieren", "verbinde", "verbinden", "setze zusammen", "baue zusammen"]},
	{"intent": "use_item", "phrases": ["benutze den", "benutze die", "benutze das", "verwende den", "verwende die", "verwende das", "setze ein", "wende an"]},
	{"intent": "move", "phrases": ["bewege dich", "beweg dich", "bewege mich", "geh zum", "geh zur", "geh zu", "gehe zum", "gehe zur", "gehe zu", "lauf zum", "lauf zur", "lauf zu", "laufe zu", "geh rueber", "geh hinueber", "geh in", "gehe in", "tritt an", "stell dich"]},
	{"intent": "look_around", "phrases": ["sieh dich um", "schau dich um", "umsehen", "was sehe ich", "beschreibe den raum", "wo bin ich"]},
	{"intent": "hints", "phrases": ["zeige objekte", "zeig objekte", "was kann ich benutzen", "zeige hinweise", "zeig mir die objekte", "objekte zeigen", "markiere objekte"]},
	{"intent": "interact", "phrases": ["oeffne", "öffne", "mach auf", "schliesse auf", "schließe auf", "nimm", "nehme", "hebe auf", "heb auf", "untersuche", "untersuch", "betrachte", "sieh dir", "schau dir", "sieh an", "schau an", "sieh", "schau", "lies", "durchsuche", "such", "suche", "druecke", "drücke", "drueck", "drück", "ziehe", "zieh", "betaetige", "betätige", "aktiviere", "schalte", "rede mit", "sprich mit", "sprechen mit", "frage", "benutze", "verwende", "repariere", "beruehre", "berühre"]},
	{"intent": "inventory", "phrases": ["inventar", "tasche", "was habe ich", "zeige inventar", "gegenstaende", "gegenstände"]},
	{"intent": "journal", "phrases": ["journal", "tagebuch", "notizen", "aufzeichnungen", "ziele"]},
	{"intent": "status", "phrases": ["status", "charakter", "eigenschaften", "werte"]},
	{"intent": "menu", "phrases": ["menue", "menü", "pause", "hauptmenue", "hauptmenü"]},
	{"intent": "save", "phrases": ["speichere", "speichern", "sicherung", "spielstand speichern"]},
	{"intent": "load", "phrases": ["lade spielstand", "laden", "letzten spielstand"]},
	{"intent": "close", "phrases": ["schliessen", "schließen", "zurueck", "zurück", "abbrechen", "beenden das fenster", "raus"]},
	{"intent": "repeat", "phrases": ["wiederhole", "nochmal sagen", "was war das", "sag das nochmal", "wiederholen"]},
	{"intent": "stop_voice", "phrases": ["sei still", "ruhe", "still", "hoer auf zu reden", "hör auf zu reden", "schweig"]},
	{"intent": "choose", "phrases": ["antworte", "antwort", "option", "waehle", "wähle", "entscheide", "nimm option", "sag"]},
	{"intent": "help", "phrases": ["was kann ich sagen", "hilfe", "befehle", "welche befehle"]}
]

const DIRECTION_WORDS := {
	"links": "links", "linke": "links", "nach links": "links",
	"rechts": "rechts", "rechte": "rechts", "nach rechts": "rechts",
	"vor": "vor", "vorne": "vor", "vorwaerts": "vor", "vorwärts": "vor", "nach vorne": "vor",
	"zurueck": "zurueck", "zurück": "zurueck", "rueckwaerts": "zurueck", "rückwärts": "zurueck"
}


static func parse(raw_text: String, context: Dictionary) -> Dictionary:
	var transcript := raw_text.strip_edges()
	var normalized := normalize(transcript)
	if normalized.is_empty():
		return _result("unknown", transcript, normalized)

	var detected := _detect_intent(normalized)
	var intent := str(detected.get("intent", "unknown"))
	var remainder := str(detected.get("remainder", normalized))

	match intent:
		"combine":
			return _resolve_two_items(intent, transcript, normalized, remainder, context)
		"use_item":
			return _resolve_item_on_target(transcript, normalized, remainder, context)
		"move":
			return _resolve_move(transcript, normalized, remainder, context)
		"interact":
			return _resolve_interact(transcript, normalized, remainder, context)
		"choose":
			return _resolve_choice(transcript, normalized, remainder, context)
		"unknown":
			return _resolve_bare(transcript, normalized, context)
		_:
			var result := _result(intent, transcript, normalized)
			result["confidence"] = 0.9
			return result


static func normalize(text: String) -> String:
	var lowered := text.to_lower()
	var cleaned := ""
	for index in range(lowered.length()):
		var character := lowered[index]
		if character in [".", ",", "!", "?", ";", ":", "\"", "'", "„", "“", "”", "-", "–", "(", ")", "\n", "\t"]:
			cleaned += " "
		else:
			cleaned += character
	while cleaned.contains("  "):
		cleaned = cleaned.replace("  ", " ")
	return cleaned.strip_edges()


static func fold(text: String) -> String:
	## ASCII folding so "oeffne" and "öffne" compare equal, whichever spelling the
	## recogniser produced.
	return text.to_lower() \
		.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue") \
		.replace("ß", "ss").replace("é", "e").replace("è", "e")


static func _detect_intent(normalized: String) -> Dictionary:
	var folded := fold(normalized)
	var best_intent := "unknown"
	var best_phrase := ""
	var best_position := -1
	for pattern in INTENT_PATTERNS:
		for phrase_value in pattern["phrases"]:
			var phrase := fold(str(phrase_value))
			var position := folded.find(phrase)
			if position < 0:
				continue
			var better := best_position < 0 \
				or position < best_position \
				or (position == best_position and phrase.length() > best_phrase.length())
			if better:
				best_intent = str(pattern["intent"])
				best_phrase = phrase
				best_position = position
		if best_position == 0:
			break
	if best_position < 0:
		return {"intent": "unknown", "remainder": normalized}
	var remainder := folded.substr(0, best_position) + " " + folded.substr(best_position + best_phrase.length())
	return {"intent": best_intent, "remainder": remainder.strip_edges(), "phrase": best_phrase}


static func _strip_fillers(text: String) -> String:
	var kept: Array[String] = []
	for token in fold(text).split(" ", false):
		var word := str(token).strip_edges()
		if word.is_empty() or fold(word) in _folded_fillers():
			continue
		kept.append(word)
	return " ".join(kept)


static func _folded_fillers() -> Array:
	var folded: Array = []
	for filler in FILLER_WORDS:
		folded.append(fold(str(filler)))
	return folded


static func _resolve_move(transcript: String, normalized: String, remainder: String, context: Dictionary) -> Dictionary:
	var phrase := _strip_fillers(remainder)
	var direction := _direction_in(phrase)
	if not direction.is_empty():
		var directional := _result("move_direction", transcript, normalized)
		directional["direction"] = direction
		directional["confidence"] = 0.85
		return directional

	var match_result := _best_target(phrase, context)
	if match_result.is_empty():
		var fallback := _result("unknown", transcript, normalized)
		fallback["reason"] = "kein_ziel"
		fallback["phrase"] = phrase
		return fallback
	var result := _result("move", transcript, normalized)
	result["target_kind"] = match_result["kind"]
	result["target"] = match_result["id"]
	result["label"] = match_result["label"]
	result["confidence"] = match_result["score"]
	return result


static func _resolve_interact(transcript: String, normalized: String, remainder: String, context: Dictionary) -> Dictionary:
	var phrase := _strip_fillers(remainder)
	var ordinal := _ordinal_in(phrase)
	if ordinal > 0 and phrase.length() <= 12:
		var by_index := _target_by_index(ordinal, context)
		if not by_index.is_empty():
			var indexed := _result("interact", transcript, normalized)
			indexed["target_kind"] = by_index["kind"]
			indexed["target"] = by_index["id"]
			indexed["label"] = by_index["label"]
			indexed["confidence"] = 0.8
			return indexed

	var match_result := _best_target(phrase, context)
	if match_result.is_empty():
		var fallback := _result("unknown", transcript, normalized)
		fallback["reason"] = "kein_ziel"
		fallback["phrase"] = phrase
		return fallback
	var result := _result("interact", transcript, normalized)
	result["target_kind"] = match_result["kind"]
	result["target"] = match_result["id"]
	result["label"] = match_result["label"]
	result["confidence"] = match_result["score"]
	return result


static func _resolve_item_on_target(transcript: String, normalized: String, remainder: String, context: Dictionary) -> Dictionary:
	var parts := _split_on_connector(remainder)
	var item_phrase := _strip_fillers(str(parts[0]))
	var target_phrase := _strip_fillers(str(parts[1]))
	var item_match := _best_item(item_phrase, context)
	if item_match.is_empty():
		# "benutze die Konsole" without a matching inventory item is a plain
		# interaction. If a target part was named, that part is the object.
		var fallback_phrase := target_phrase if not target_phrase.is_empty() else remainder
		return _resolve_interact(transcript, normalized, fallback_phrase, context)
	var result := _result("use_item", transcript, normalized)
	result["item"] = item_match["id"]
	result["item_label"] = item_match["label"]
	result["confidence"] = item_match["score"]
	if target_phrase.is_empty():
		result["intent"] = "select_item"
		return result
	var target_match := _best_target(target_phrase, context)
	if target_match.is_empty():
		result["intent"] = "select_item"
		return result
	result["target_kind"] = target_match["kind"]
	result["target"] = target_match["id"]
	result["label"] = target_match["label"]
	result["confidence"] = minf(float(result["confidence"]), float(target_match["score"]))
	return result


static func _resolve_two_items(intent: String, transcript: String, normalized: String, remainder: String, context: Dictionary) -> Dictionary:
	var parts := _split_on_connector(remainder)
	var first := _best_item(_strip_fillers(str(parts[0])), context)
	var second := _best_item(_strip_fillers(str(parts[1])), context)
	if first.is_empty() or second.is_empty():
		var fallback := _result("unknown", transcript, normalized)
		fallback["reason"] = "kombination_unklar"
		return fallback
	var result := _result(intent, transcript, normalized)
	result["item"] = first["id"]
	result["item_label"] = first["label"]
	result["secondary"] = second["id"]
	result["secondary_label"] = second["label"]
	result["confidence"] = minf(float(first["score"]), float(second["score"]))
	return result


static func _resolve_choice(transcript: String, normalized: String, remainder: String, context: Dictionary) -> Dictionary:
	var options: Array = context.get("options", [])
	var phrase := _strip_fillers(remainder)
	var ordinal := _ordinal_in(phrase)
	if ordinal > 0 and ordinal <= options.size():
		var picked: Dictionary = options[ordinal - 1]
		var result := _result("choose", transcript, normalized)
		result["target"] = str(picked.get("id", ""))
		result["label"] = str(picked.get("label", ""))
		result["confidence"] = 0.9
		return result
	var best_score := 0.0
	var best_option: Dictionary = {}
	for option_value in options:
		if not option_value is Dictionary:
			continue
		var option: Dictionary = option_value
		var score := similarity(phrase, str(option.get("label", "")))
		if score > best_score:
			best_score = score
			best_option = option
	if best_option.is_empty() or best_score < ACCEPT_THRESHOLD:
		var fallback := _result("unknown", transcript, normalized)
		fallback["reason"] = "keine_option"
		return fallback
	var chosen := _result("choose", transcript, normalized)
	chosen["target"] = str(best_option.get("id", ""))
	chosen["label"] = str(best_option.get("label", ""))
	chosen["confidence"] = best_score
	return chosen


static func _resolve_bare(transcript: String, normalized: String, context: Dictionary) -> Dictionary:
	## No verb was recognised. A bare object name still reads as "interact with
	## it", and a bare number answers a pending question.
	var options: Array = context.get("options", [])
	var phrase := _strip_fillers(normalized)
	var ordinal := _ordinal_in(phrase)
	if not options.is_empty():
		if ordinal > 0 and ordinal <= options.size():
			return _resolve_choice(transcript, normalized, phrase, context)
		var choice := _resolve_choice(transcript, normalized, phrase, context)
		if str(choice.get("intent", "")) == "choose":
			return choice

	var direction := _direction_in(phrase)
	if not direction.is_empty():
		var directional := _result("move_direction", transcript, normalized)
		directional["direction"] = direction
		directional["confidence"] = 0.7
		return directional

	var match_result := _best_target(phrase, context)
	if not match_result.is_empty() and float(match_result["score"]) >= STRONG_THRESHOLD:
		var result := _result("interact", transcript, normalized)
		result["target_kind"] = match_result["kind"]
		result["target"] = match_result["id"]
		result["label"] = match_result["label"]
		result["confidence"] = match_result["score"]
		return result
	var unknown := _result("unknown", transcript, normalized)
	unknown["phrase"] = phrase
	return unknown


static func _split_on_connector(text: String) -> Array:
	var folded := fold(text)
	# Deutsche Verschmelzungen mitzaehlen: "am Terminal" ist so haeufig wie
	# "an dem Terminal", und ohne sie faellt das Ziel unter den Tisch.
	for connector in [
			" mit ", " auf ", " aufs ", " an ", " am ", " ans ", " in ", " im ", " ins ",
			" gegen ", " bei ", " beim ", " zum ", " zur ", " durch "
		]:
		var position := folded.find(connector)
		if position > 0:
			return [folded.substr(0, position), folded.substr(position + connector.length())]
	return [folded, ""]


static func _direction_in(phrase: String) -> String:
	var folded := fold(phrase)
	for key in DIRECTION_WORDS:
		if folded == fold(str(key)) or folded.begins_with(fold(str(key)) + " ") or folded.ends_with(" " + fold(str(key))):
			return str(DIRECTION_WORDS[key])
	return ""


static func _ordinal_in(phrase: String) -> int:
	for token in fold(phrase).split(" ", false):
		var word := str(token)
		if word.is_valid_int():
			return int(word)
		for key in NUMBER_WORDS:
			if fold(str(key)) == word:
				return int(NUMBER_WORDS[key])
	return 0


static func _target_by_index(ordinal: int, context: Dictionary) -> Dictionary:
	var hotspots: Array = context.get("hotspots", [])
	if ordinal >= 1 and ordinal <= hotspots.size():
		var hotspot: Dictionary = hotspots[ordinal - 1]
		return {"kind": "hotspot", "id": str(hotspot.get("id", "")), "label": str(hotspot.get("label", "")), "score": 0.8}
	var exits: Array = context.get("exits", [])
	var exit_index := ordinal - hotspots.size()
	if exit_index >= 1 and exit_index <= exits.size():
		var exit_data: Dictionary = exits[exit_index - 1]
		return {"kind": "exit", "id": str(exit_data.get("id", "")), "label": str(exit_data.get("label", "")), "score": 0.8}
	return {}


static func _best_target(phrase: String, context: Dictionary) -> Dictionary:
	if phrase.strip_edges().is_empty():
		return {}
	var best: Dictionary = {}
	var best_score := 0.0
	for entry_value in context.get("hotspots", []):
		if not entry_value is Dictionary:
			continue
		var entry: Dictionary = entry_value
		var score := similarity(phrase, str(entry.get("label", "")))
		score = maxf(score, similarity(phrase, _id_to_words(str(entry.get("id", "")))) * 0.92)
		if score > best_score:
			best_score = score
			best = {"kind": "hotspot", "id": str(entry.get("id", "")), "label": str(entry.get("label", "")), "score": score}
	for entry_value in context.get("exits", []):
		if not entry_value is Dictionary:
			continue
		var entry: Dictionary = entry_value
		var score := similarity(phrase, str(entry.get("label", "")))
		score = maxf(score, similarity(phrase, _id_to_words(str(entry.get("id", "")))) * 0.92)
		if score > best_score:
			best_score = score
			best = {"kind": "exit", "id": str(entry.get("id", "")), "label": str(entry.get("label", "")), "score": score}
	if best_score < ACCEPT_THRESHOLD:
		return {}
	return best


static func _best_item(phrase: String, context: Dictionary) -> Dictionary:
	if phrase.strip_edges().is_empty():
		return {}
	var best: Dictionary = {}
	var best_score := 0.0
	for entry_value in context.get("items", []):
		if not entry_value is Dictionary:
			continue
		var entry: Dictionary = entry_value
		var label := str(entry.get("name", entry.get("label", "")))
		var score := similarity(phrase, label)
		score = maxf(score, similarity(phrase, _id_to_words(str(entry.get("id", "")))) * 0.92)
		if score > best_score:
			best_score = score
			best = {"id": str(entry.get("id", "")), "label": label, "score": score}
	if best_score < ACCEPT_THRESHOLD:
		return {}
	return best


static func _id_to_words(identifier: String) -> String:
	return identifier.replace("_", " ").replace("-", " ")


static func similarity(spoken: String, candidate: String) -> float:
	## Combines token containment with edit distance. Containment carries most of
	## the weight because German compounds ("Medizinschrank") are often spoken in
	## a shortened form ("Schrank").
	var left := fold(spoken).strip_edges()
	var right := fold(candidate).strip_edges()
	if left.is_empty() or right.is_empty():
		return 0.0
	if left == right:
		return 1.0

	var left_tokens := left.split(" ", false)
	var right_tokens := right.split(" ", false)
	var matched := 0
	for spoken_token_value in left_tokens:
		var spoken_token := str(spoken_token_value)
		if spoken_token.length() < 3:
			continue
		for candidate_token_value in right_tokens:
			var candidate_token := str(candidate_token_value)
			if candidate_token.length() < 3:
				continue
			if candidate_token.contains(spoken_token) or spoken_token.contains(candidate_token):
				matched += 1
				break
			if _edit_distance(spoken_token, candidate_token) <= 1:
				matched += 1
				break
	var significant := 0
	for token_value in left_tokens:
		if str(token_value).length() >= 3:
			significant += 1
	var containment := 0.0
	if significant > 0:
		containment = float(matched) / float(significant)

	var distance := _edit_distance(left, right)
	var longest := float(maxi(left.length(), right.length()))
	var closeness := 1.0 - float(distance) / maxf(longest, 1.0)
	return clampf(containment * 0.72 + closeness * 0.28, 0.0, 1.0)


static func _edit_distance(left: String, right: String) -> int:
	var left_length := left.length()
	var right_length := right.length()
	if left_length == 0:
		return right_length
	if right_length == 0:
		return left_length
	var previous: Array[int] = []
	previous.resize(right_length + 1)
	for index in range(right_length + 1):
		previous[index] = index
	for row in range(1, left_length + 1):
		var current: Array[int] = []
		current.resize(right_length + 1)
		current[0] = row
		for column in range(1, right_length + 1):
			var cost := 0 if left[row - 1] == right[column - 1] else 1
			current[column] = mini(
				mini(current[column - 1] + 1, previous[column] + 1),
				previous[column - 1] + cost
			)
		previous = current
	return previous[right_length]


static func _result(intent: String, transcript: String, normalized: String) -> Dictionary:
	return {
		"intent": intent,
		"transcript": transcript,
		"normalized": normalized,
		"target": "",
		"target_kind": "",
		"label": "",
		"item": "",
		"secondary": "",
		"direction": "",
		"confidence": 0.0
	}
