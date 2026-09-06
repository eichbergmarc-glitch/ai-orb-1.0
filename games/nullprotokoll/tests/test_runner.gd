extends Node

var failures: Array[String] = []
var completed := false

func _ready() -> void:
	await get_tree().process_frame
	# Ein Laufzeitfehler mitten im Test bricht nur die Funktion ab. Ohne diese
	# beiden Wachen meldet der Runner danach faelschlich "bestanden".
	if get_node_or_null("/root/GameManager") == null:
		failures.append("Autoload GameManager wurde nicht geladen; das Projekt ist nicht lauffaehig.")
	else:
		_run_vertical_slice()
		if not completed:
			failures.append("Der Testlauf wurde vorzeitig abgebrochen. Siehe die Fehlerausgabe darueber.")
	if failures.is_empty():
		print("NULLPROTOKOLL – GDScript-Integrationstest bestanden")
		print("  Kompletter Pfad und alle vier Prologausgänge ausgeführt")
		print("  Speichern, Laden und Entscheidungskontrollpunkt geprüft")
		get_tree().quit(0)
	else:
		printerr("GDScript-Integrationstest fehlgeschlagen (%d):" % failures.size())
		for failure in failures:
			printerr("- " + failure)
		get_tree().quit(1)

func _run_vertical_slice() -> void:
	_expect(GameManager.data_ready, "Story-, Dialog- oder Inventardaten konnten nicht geladen werden.")
	GameManager.save_manager.set_test_mode(true)
	var profile := {"name": "Test Vale", "presentation": "weiblich", "logic": 1, "empathy": 3, "instinct": 2}
	_expect(GameManager.new_game(profile, 424242), "Neues Spiel konnte nicht gestartet werden.")
	_expect(_location_is("krankenstation"), "Startort ist nicht die Aufwachkammer.")

	GameManager.interact("mira_terminal")
	GameManager.choose_dialogue("trust")
	GameManager.choose_dialogue("end_guided")
	_expect(GameManager.state["flags"].has("met_mira"), "Erstkontakt mit MIRA wurde nicht gespeichert.")
	GameManager.interact("treatment_bed")
	GameManager.interact("medical_cabinet")
	_expect(GameManager.combine_items("badge_cracked", "film_conductive").get("success", false), "Zugangskarte ließ sich nicht reparieren.")
	_use("badge_repaired", "sealed_door")
	_expect(GameManager.state["flags"].has("chamber_open"), "Kammertür blieb nach Kartennutzung geschlossen.")
	_expect(GameManager.travel("to_diagnostics").get("success", false), "Diagnostiklabor ist nicht erreichbar.")

	GameManager.interact("radio_case")
	GameManager.interact("neural_scanner")
	GameManager.interact("open_frequency")
	GameManager.choose_dialogue("who")
	GameManager.choose_dialogue("end_name")
	_expect(GameManager.state["flags"].has("met_samir"), "Samirs Erstkontakt wurde nicht gespeichert.")
	_expect(GameManager.travel("to_rotunda").get("success", false), "Sicherheitsrotunde ist nicht erreichbar.")
	_expect(GameManager.travel("to_maintenance").get("success", false), "Wartungsgalerie ist nicht erreichbar.")

	for hotspot_id in ["emergency_lamp", "warning_beacon", "tool_wall", "broken_speaker", "parts_cabinet", "workbench_notes"]:
		GameManager.interact(hotspot_id)
	_expect(GameManager.combine_items("cell_empty", "capacitor_charged").get("success", false), "Überbrückungszelle ließ sich nicht bauen.")
	_expect(GameManager.combine_items("fiber_cord", "speaker_magnet").get("success", false), "Bergungsleine ließ sich nicht bauen.")
	_expect(GameManager.combine_items("radio_broken", "crypto_module").get("success", false), "Gesichertes Funkgerät ließ sich nicht bauen.")
	GameManager.interact("secure_frequency")
	GameManager.choose_dialogue("plan")
	GameManager.choose_dialogue("end_plan")
	_expect(GameManager.state["flags"].has("secure_channel"), "Sicherer Kanal wurde nicht freigeschaltet.")
	_expect(GameManager.travel("back_rotunda").get("success", false), "Rückweg zur Rotunde scheiterte.")

	_use("retrieval_line", "floor_grate")
	_expect(GameManager.inventory.has_item("service_key"), "Serviceschlüssel wurde nicht geborgen.")
	_use("bridge_cell", "manual_distributor")
	_expect(GameManager.state["flags"].has("power_bridge_installed"), "Stromverteiler blieb ohne Startimpuls.")
	GameManager.interact("power_priority")
	GameManager.choose_interaction("power_priority", "archive_first")
	_expect(GameManager.state["flags"].has("power_archive"), "Archiv erhielt keinen Strom.")

	_expect(GameManager.travel("to_quarantine").get("success", false), "Quarantäne ist trotz Schlüssel und Strom nicht erreichbar.")
	GameManager.interact("juna_glass")
	GameManager.choose_dialogue("release_now")
	GameManager.choose_dialogue("end_released")
	_expect(GameManager.state["flags"].has("juna_free"), "Juna wurde nicht freigelassen.")
	_expect(GameManager.inventory.has_item("isolation_token"), "Isolationstoken fehlt nach Junas Entscheidung.")
	GameManager.travel("back_rotunda")
	_expect(GameManager.travel("to_archive").get("success", false), "Kaltarchiv ist trotz Schlüssel und Strom nicht erreichbar.")

	GameManager.interact("audit_core_intact")
	GameManager.interact("rack_marks")
	GameManager.interact("mirror_compartment")
	_expect(GameManager.inventory.has_item("audit_wafer"), "Audit-Wafer wurde nicht gesichert.")
	_expect(GameManager.inventory.has_item("mirror_module"), "Spiegelmodul wurde nicht gefunden.")
	_expect(GameManager.combine_items("isolation_token", "mirror_module").get("success", false), "Sandbox-Brücke ließ sich nicht bauen.")
	GameManager.travel("back_rotunda")
	_expect(GameManager.travel("to_uplink").get("success", false), "Relaiskern blieb trotz gelöstem Archiv und Juna-Entscheidung gesperrt.")
	_expect(not GameManager.save_manager.load_checkpoint().is_empty(), "Kontrollpunkt vor der Schlussentscheidung fehlt.")

	var final_view := GameManager.interact("final_console")
	_expect(final_view.get("choices", []).size() == 4, "Verborgener vierter Ausgang ist im qualifizierten Pfad nicht sichtbar.")
	var ending_result := GameManager.choose_interaction("final_console", "sandbox_mira")
	_expect(str(ending_result.get("ending", "")) == "sandbox_mira", "Sandbox-Ende wurde nicht ausgelöst.")
	_expect(str(GameManager.state.get("ending", "")) == "sandbox_mira", "Endzustand wurde nicht im Spielstatus gespeichert.")

	GameManager.state["ending"] = ""
	GameManager.inventory.reset()
	_expect(GameManager.load_game(), "Spielstand ließ sich nicht laden.")
	_expect(str(GameManager.state.get("ending", "")) == "sandbox_mira", "Geladener Spielstand enthält nicht das erreichte Ende.")
	_expect(GameManager.inventory.has_item("sandbox_bridge"), "Inventar wurde beim Laden nicht wiederhergestellt.")
	_expect(GameManager.load_checkpoint(), "Entscheidungskontrollpunkt ließ sich nicht laden.")
	_expect(str(GameManager.state.get("ending", "")).is_empty(), "Kontrollpunkt liegt nicht vor der Schlussentscheidung.")
	_expect(_location_is("relaiskern"), "Kontrollpunkt stellt nicht den Relaiskern wieder her.")
	for ending_case in [["upload_mira", "upload_mira"], ["sever_uplink", "sever_uplink"], ["broadcast_audit", "broadcast_audit"]]:
		_expect(GameManager.load_checkpoint(), "Kontrollpunkt konnte für einen Grundausgang nicht erneut geladen werden.")
		var base_result := GameManager.choose_interaction("final_console", ending_case[0])
		_expect(str(base_result.get("ending", "")) == ending_case[1], "Grundausgang %s wurde nicht erreicht." % ending_case[1])
	_expect(GameManager.load_checkpoint(), "Abschließende Wiederherstellung des Kontrollpunkts scheiterte.")
	completed = true

func _use(item_id: String, hotspot_id: String) -> void:
	GameManager.inventory.selected_item_id = item_id
	var result := GameManager.interact(hotspot_id)
	_expect(result.get("success", false), "%s konnte nicht an %s benutzt werden." % [item_id, hotspot_id])

func _location_is(location_id: String) -> bool:
	return str(GameManager.state.get("world", {}).get("current_location", "")) == location_id

func _expect(condition: bool, message: String) -> void:
	if not condition:
		failures.append(message)
