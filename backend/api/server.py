"""Die HTTP-API von AI-Orb.

Definiert alle Endpunkte, über die das Electron-Frontend mit dem Backend
spricht. Die Endpunkte greifen niemals direkt auf Fachmodule zu, sondern
ausschließlich über die :class:`~backend.runtime.Runtime` und damit über
das Cognitive Core.

Der Server lauscht ausschließlich auf ``127.0.0.1``.
"""

from __future__ import annotations

from typing import Any

from backend import __version__
from backend.api.http_server import ApiRouter, LocalApiServer, SseBroker
from backend.config import get_config
from backend.events.event_bus import WILDCARD, Event
from backend.runtime import Runtime
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


def build_router(runtime: Runtime) -> ApiRouter:
    """Erstellt die Routing-Tabelle der API.

    Args:
        runtime: Die laufende AI-Orb Runtime.

    Returns:
        Der befüllte Router.
    """

    router = ApiRouter()

    # --- Status und Diagnose ------------------------------------------------

    def health(_: dict[str, Any]) -> dict[str, Any]:
        """Einfacher Statusendpunkt für das Startskript."""

        return {"status": "ok", "version": __version__}

    def status(_: dict[str, Any]) -> dict[str, Any]:
        """Vollständiger Systemstatus."""

        return runtime.status()

    def config_view(_: dict[str, Any]) -> dict[str, Any]:
        """Gibt die aktuelle Konfiguration an das Frontend."""

        return get_config().raw

    # --- Die Rueckkehr von der Google-Anmeldung -----------------------------
    #
    # Google schickt den Browser nach der Zustimmung auf
    # http://127.0.0.1:8756/gmail/callback?code=... zurueck. Diese Route
    # FEHLTE: Am 17.08.2026 stand der Benutzer mit dem Einmalcode in der
    # Adresszeile vor einem {"error": "not_found"} - er hatte alles richtig
    # gemacht, und niemand nahm den Code an. Hier wird er angenommen, gegen
    # das Token getauscht und dem Benutzer im Browser gesagt, woran er ist.

    def gmail_callback(params: dict[str, Any]) -> dict[str, Any]:
        def _seite(titel: str, text: str, gut: bool) -> dict[str, Any]:
            farbe = "#2e9e5b" if gut else "#c0392b"
            return {
                "_html": (
                    "<!DOCTYPE html><html lang='de'><head><meta charset='utf-8'>"
                    "<title>AI-Orb</title></head>"
                    "<body style='font-family:Segoe UI,system-ui,sans-serif;"
                    "background:#0e1420;color:#dce8f7;display:flex;"
                    "align-items:center;justify-content:center;height:100vh;margin:0'>"
                    "<div style='max-width:30rem;text-align:center'>"
                    f"<h1 style='color:{farbe};font-size:1.4rem'>{titel}</h1>"
                    f"<p style='line-height:1.6'>{text}</p></div></body></html>"
                ),
                "_status": 200 if gut else 400,
            }

        agent = getattr(runtime, "gmail", None)
        if agent is None:
            return _seite(
                "Gmail ist nicht eingerichtet",
                "Der Orb hat kein Gmail-Modul geladen. Einzelheiten stehen im "
                "Protokoll.",
                gut=False,
            )

        if params.get("error"):
            return _seite(
                "Anmeldung abgebrochen",
                f"Google meldet: {params['error']}. Du kannst dieses Fenster "
                "schliessen und es im Orb erneut versuchen.",
                gut=False,
            )

        ergebnis = agent.complete_login(str(params.get("code", "")))
        if not ergebnis.get("ok"):
            return _seite(
                "Anmeldung fehlgeschlagen",
                str(ergebnis.get("fehler", "Unbekannter Fehler.")),
                gut=False,
            )

        # Dem Orb Bescheid geben, damit er es auch SAGT - der Benutzer
        # sieht sonst nur den Browser und fragt sich, ob der Orb es weiss.
        with_kalender = bool(ergebnis.get("kalender"))
        runtime.publish(
            "gmail.login.completed", {"kalender": with_kalender}
        )
        zusatz = (
            " Auch der Kalender ist freigegeben."
            if with_kalender
            else " Der Kalender ist NICHT dabei - dann fehlte der Haken auf "
                 "der Google-Seite."
        )
        return _seite(
            "Anmeldung erfolgreich",
            "Der Orb ist jetzt mit deinem Google-Konto verbunden." + zusatz +
            " Du kannst dieses Fenster schliessen.",
            gut=True,
        )

    router.get("/gmail/callback", gmail_callback)

    router.get("/health", health)
    router.get("/status", status)
    router.get("/config", config_view)

    def provider_mode(body: dict[str, Any]) -> dict[str, Any]:
        """Schaltet denselben Modus wie der Sprachbefehl ueber die lokale API."""

        mode = str(body.get("mode", "")).strip()
        return runtime.run(runtime.providers.set_operating_mode(mode))

    router.post("/providers/mode", provider_mode)

    # --- Gespräch --------------------------------------------------------------

    def ask(body: dict[str, Any]) -> dict[str, Any]:
        """Verarbeitet eine Benutzereingabe."""

        text = str(body.get("text", "")).strip()
        if not text:
            return {"error": "leere_eingabe", "response": "Ich habe keine Eingabe erhalten."}
        response = runtime.run(runtime.ask(text))
        return response.to_dict()

    def end_conversation(_: dict[str, Any]) -> dict[str, Any]:
        """Beendet die laufende Unterhaltung und sichert die Zusammenfassung."""

        summary = runtime.run(runtime.orchestrator.end_conversation())
        return {"ended": True, "summary": summary or ""}

    def history(_: dict[str, Any]) -> dict[str, Any]:
        """Gibt den Verlauf der laufenden Unterhaltung zurück."""

        return {"messages": runtime.orchestrator.conversations.history()}

    router.post("/ask", ask)
    router.post("/conversation/end", end_conversation)
    router.get("/conversation/history", history)

    # --- Projekte ---------------------------------------------------------------

    def projects_list(_: dict[str, Any]) -> dict[str, Any]:
        return {"projects": runtime.cognitive.projects.overview()}

    def project_create(body: dict[str, Any]) -> dict[str, Any]:
        name = str(body.get("name", "")).strip()
        if not name:
            return {"created": False, "message": "Es wurde kein Projektname angegeben."}
        project = runtime.cognitive.project_engine.create(
            name,
            path=body.get("path"),
            kind=str(body.get("kind", "allgemein")),
        )
        return {"created": True, "project": project}

    def project_activate(body: dict[str, Any]) -> dict[str, Any]:
        project_id = str(body.get("project_id", ""))
        if project_id:
            return runtime.cognitive.project_engine.activate(project_id)
        return runtime.cognitive.projects.activate_by_name(str(body.get("name", "")))

    def project_detect(body: dict[str, Any]) -> dict[str, Any]:
        path = str(body.get("path", ""))
        if not path:
            return {"created": False, "message": "Es wurde kein Pfad angegeben."}
        return runtime.cognitive.project_engine.detect_and_register(
            path, auto_confirm=bool(body.get("confirmed", False))
        )

    def project_summary(_: dict[str, Any]) -> dict[str, Any]:
        return {"summary": runtime.cognitive.projects.summary_text()}

    def project_graph(body: dict[str, Any]) -> dict[str, Any]:
        project_id = str(body.get("project_id") or runtime.cognitive.projects.active_id() or "")
        if not project_id:
            return {"nodes": [], "edges": []}
        return runtime.cognitive.project_engine.graph.as_dict(project_id)

    def project_delete(body: dict[str, Any]) -> dict[str, Any]:
        return runtime.cognitive.project_engine.delete(str(body.get("project_id", "")))

    router.get("/projects", projects_list)
    router.post("/projects/create", project_create)
    router.post("/projects/activate", project_activate)
    router.post("/projects/detect", project_detect)
    router.get("/projects/summary", project_summary)
    router.post("/projects/graph", project_graph)
    router.post("/projects/delete", project_delete)

    # --- Aufgaben und Ziele --------------------------------------------------------

    def tasks_list(_: dict[str, Any]) -> dict[str, Any]:
        project_id = runtime.cognitive.projects.active_id()
        return {
            "overview": runtime.cognitive.tasks.overview(project_id),
            "tasks": [
                task.to_dict() for task in runtime.cognitive.tasks.list(project_id=project_id)
            ],
        }

    def task_add(body: dict[str, Any]) -> dict[str, Any]:
        title = str(body.get("title", "")).strip()
        if not title:
            return {"added": False, "message": "Es wurde kein Aufgabentitel angegeben."}
        if bool(body.get("decompose", False)):
            created = runtime.cognitive.tasks.decompose(
                title, project_id=runtime.cognitive.projects.active_id()
            )
            return {"added": True, "tasks": [task.to_dict() for task in created]}
        task = runtime.cognitive.tasks.add(
            title,
            project_id=runtime.cognitive.projects.active_id(),
            priority=str(body.get("priority", "normal")),
        )
        return {"added": True, "task": task.to_dict()}

    def task_status(body: dict[str, Any]) -> dict[str, Any]:
        changed = runtime.cognitive.tasks.set_status(
            str(body.get("task_id", "")),
            str(body.get("status", "offen")),
            reason=body.get("reason"),
        )
        return {"changed": changed}

    def goals_list(_: dict[str, Any]) -> dict[str, Any]:
        return runtime.cognitive.goals.overview()

    def goal_add(body: dict[str, Any]) -> dict[str, Any]:
        title = str(body.get("title", "")).strip()
        if not title:
            return {"added": False, "message": "Es wurde kein Ziel angegeben."}
        goal = runtime.cognitive.goals.add(
            title,
            horizon=str(body.get("horizon", "projekt")),
            priority=str(body.get("priority", "normal")),
            project_id=runtime.cognitive.projects.active_id(),
        )
        return {"added": True, "goal": goal}

    router.get("/tasks", tasks_list)
    router.post("/tasks/add", task_add)
    router.post("/tasks/status", task_status)
    router.get("/goals", goals_list)
    router.post("/goals/add", goal_add)

    # --- Gedächtnis -------------------------------------------------------------------

    def memory_list(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "statistics": runtime.memory.statistics(),
            "entries": [record.to_dict() for record in runtime.memory.all()[:200]],
        }

    def memory_search(body: dict[str, Any]) -> dict[str, Any]:
        query = str(body.get("query", ""))
        results = runtime.memory.recall(query, limit=int(body.get("limit", 10)))
        return {
            "results": [
                {**result.record.to_dict(), "relevance": round(result.score, 3)}
                for result in results
            ]
        }

    def memory_delete(body: dict[str, Any]) -> dict[str, Any]:
        return {"deleted": runtime.memory.forget(str(body.get("id", "")))}

    def memory_edit(body: dict[str, Any]) -> dict[str, Any]:
        return {
            "changed": runtime.memory.edit(str(body.get("id", "")), str(body.get("content", "")))
        }

    router.get("/memory", memory_list)
    router.post("/memory/search", memory_search)
    router.post("/memory/delete", memory_delete)
    router.post("/memory/edit", memory_edit)

    # --- Orb-Verhalten und Fenster -----------------------------------------------------

    def orb_state(body: dict[str, Any]) -> dict[str, Any]:
        """Meldet einen Zustandswechsel des Orb an das Backend."""

        state = str(body.get("state", "idle"))
        runtime.publish("orb.state.changed", {"state": state})
        return {"state": state}

    def orb_interaction(body: dict[str, Any]) -> dict[str, Any]:
        """Meldet eine Benutzerinteraktion mit dem Orb."""

        runtime.publish("orb.action.triggered", dict(body))
        return {"received": True}

    def behavior_position(body: dict[str, Any]) -> dict[str, Any]:
        """Vermerkt eine Orb-Position für das Lernsystem."""

        preference = runtime.behavior.record_position(
            x=float(body.get("x", 0)),
            y=float(body.get("y", 0)),
            screen_width=float(body.get("screen_width", 1920)),
            screen_height=float(body.get("screen_height", 1080)),
            monitor=int(body.get("monitor", 0)),
            manual=bool(body.get("manual", False)),
            program=body.get("program"),
        )
        return {"recorded": True, "preference": preference.to_dict()}

    def behavior_score(body: dict[str, Any]) -> dict[str, Any]:
        """Bewertet eine Kandidatenposition anhand des gelernten Verhaltens."""

        score = runtime.behavior.preference_score(
            x=float(body.get("x", 0)),
            y=float(body.get("y", 0)),
            screen_width=float(body.get("screen_width", 1920)),
            screen_height=float(body.get("screen_height", 1080)),
            monitor=int(body.get("monitor", 0)),
            program=body.get("program"),
        )
        return {"score": round(score, 4)}

    def behavior_snapshot(_: dict[str, Any]) -> dict[str, Any]:
        return runtime.behavior.snapshot()

    def behavior_activity(body: dict[str, Any]) -> dict[str, Any]:
        runtime.behavior.record_activity(program=body.get("program"))
        return {"recorded": True}

    router.post("/orb/state", orb_state)
    router.post("/orb/interaction", orb_interaction)
    router.post("/behavior/position", behavior_position)
    router.post("/behavior/score", behavior_score)
    router.post("/behavior/activity", behavior_activity)
    router.get("/behavior", behavior_snapshot)

    # --- Agenten, Skills, Evolution -------------------------------------------------------

    def agents_status(_: dict[str, Any]) -> dict[str, Any]:
        return runtime.agents.status()

    def agents_explain(_: dict[str, Any]) -> dict[str, Any]:
        return runtime.agents.explain_last()

    def skills_status(_: dict[str, Any]) -> dict[str, Any]:
        return runtime.skills.status()

    def skills_catalog(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "entries": [entry.to_dict() for entry in runtime.skills.marketplace.entries()],
            "categories": runtime.skills.marketplace.categories(),
        }

    def skill_prepare(body: dict[str, Any]) -> dict[str, Any]:
        proposal = runtime.skills.prepare_install(str(body.get("path", "")))
        return proposal.to_dict()

    def skill_install(body: dict[str, Any]) -> dict[str, Any]:
        proposal = runtime.skills.prepare_install(str(body.get("path", "")))
        return runtime.skills.install(proposal, confirmed=bool(body.get("confirmed", False)))

    def skill_activate(body: dict[str, Any]) -> dict[str, Any]:
        return runtime.run(runtime.skills.activate(str(body.get("name", ""))))

    def skill_deactivate(body: dict[str, Any]) -> dict[str, Any]:
        return runtime.run(runtime.skills.deactivate(str(body.get("name", ""))))

    def skill_permission(body: dict[str, Any]) -> dict[str, Any]:
        name = str(body.get("name", ""))
        permission = str(body.get("permission", ""))
        if bool(body.get("grant", True)):
            return runtime.skills.grant(name, permission)
        return runtime.skills.revoke(name, permission)

    def evolution_analyze(_: dict[str, Any]) -> dict[str, Any]:
        usage = {
            "programs": dict(runtime.behavior.top_programs(limit=10)),
            "missing_capabilities": [],
        }
        return runtime.evolution.analyze(usage=usage)

    def evolution_report(_: dict[str, Any]) -> dict[str, Any]:
        return runtime.evolution.report()

    def evolution_apply(body: dict[str, Any]) -> dict[str, Any]:
        return runtime.evolution.apply_patch(
            str(body.get("patch_id", "")), confirmed=bool(body.get("confirmed", False))
        )

    def evolution_undo(_: dict[str, Any]) -> dict[str, Any]:
        return runtime.evolution.undo_last_change()

    router.get("/agents", agents_status)
    router.get("/agents/explain", agents_explain)
    router.get("/skills", skills_status)
    router.get("/skills/catalog", skills_catalog)
    router.post("/skills/prepare", skill_prepare)
    router.post("/skills/install", skill_install)
    router.post("/skills/activate", skill_activate)
    router.post("/skills/deactivate", skill_deactivate)
    router.post("/skills/permission", skill_permission)
    router.post("/evolution/analyze", evolution_analyze)
    router.get("/evolution/report", evolution_report)
    router.post("/evolution/apply", evolution_apply)
    router.post("/evolution/undo", evolution_undo)

    # --- Sicherheit und Zustimmung -----------------------------------------------
    # Über diese Endpunkte beantwortet die Oberfläche die Fragen, die die
    # Sicherheitsschicht stellt. Ohne sie bliebe jede heikle Aktion
    # unbeantwortet und liefe in die Zeitüberschreitung – also in ein Nein.

    def security_status(_: dict[str, Any]) -> dict[str, Any]:
        return runtime.security.status()

    def security_permissions(_: dict[str, Any]) -> dict[str, Any]:
        return {"permissions": runtime.security.catalog()}

    def consent_pending(_: dict[str, Any]) -> dict[str, Any]:
        return {"pending": runtime.security.consent.pending()}

    def consent_resolve(body: dict[str, Any]) -> dict[str, Any]:
        resolved = runtime.security.consent.resolve(
            str(body.get("request_id", "")),
            bool(body.get("granted", False)),
            remember=bool(body.get("remember", False)),
            reason=str(body.get("reason", "")),
        )
        return {"resolved": resolved}

    def consent_revoke(body: dict[str, Any]) -> dict[str, Any]:
        if bool(body.get("all", False)):
            return {"revoked": runtime.security.consent.revoke_all()}
        revoked = runtime.security.consent.revoke(
            str(body.get("actor", "")), str(body.get("permission", ""))
        )
        return {"revoked": 1 if revoked else 0}

    def consent_remembered(_: dict[str, Any]) -> dict[str, Any]:
        return {"granted": runtime.security.consent.remembered()}

    def audit_log(body: dict[str, Any]) -> dict[str, Any]:
        return {
            "entries": runtime.security.audit.recent(
                limit=int(body.get("limit", 50)),
                permission=str(body.get("permission", "")),
            )
        }

    router.get("/security", security_status)
    router.get("/security/permissions", security_permissions)
    router.get("/security/consent", consent_pending)
    router.post("/security/consent", consent_resolve)
    router.post("/security/revoke", consent_revoke)
    router.get("/security/remembered", consent_remembered)
    router.post("/security/audit", audit_log)

    # --- Sprachsteuerung ----------------------------------------------------------

    def voice_status(_: dict[str, Any]) -> dict[str, Any]:
        return runtime.voice.status()

    def voice_start(_: dict[str, Any]) -> dict[str, Any]:
        started = runtime.run(runtime.voice.start(), timeout=60.0)
        return {"started": started, "report": runtime.voice.requirements_report()}

    def voice_stop(_: dict[str, Any]) -> dict[str, Any]:
        runtime.run(runtime.voice.stop(), timeout=30.0)
        return {"stopped": True}

    def voice_say(body: dict[str, Any]) -> dict[str, Any]:
        text = str(body.get("text", "")).strip()
        if not text:
            return {"spoken": False, "message": "Es wurde kein Text angegeben."}
        spoken = runtime.run(
            runtime.voice.say(text, emotion=str(body.get("emotion", ""))), timeout=120.0
        )
        return {"spoken": spoken}

    def voice_interrupt(_: dict[str, Any]) -> dict[str, Any]:
        runtime.voice.interrupt()
        return {"interrupted": True}

    def voice_history(_: dict[str, Any]) -> dict[str, Any]:
        return {"turns": runtime.voice.history()}

    router.get("/voice", voice_status)
    router.post("/voice/start", voice_start)
    router.post("/voice/stop", voice_stop)
    router.post("/voice/say", voice_say)
    router.post("/voice/interrupt", voice_interrupt)
    router.get("/voice/history", voice_history)

    # --- Werkzeuge, Plugins, Arbeitsabläufe ------------------------------------------

    def tools_list(_: dict[str, Any]) -> dict[str, Any]:
        return {"tools": runtime.tools.catalog(), "engine": runtime.tool_engine.status()}

    def plugins_list(_: dict[str, Any]) -> dict[str, Any]:
        return {"plugins": runtime.plugins.catalog(), "status": runtime.plugins.status()}

    def plugin_load(body: dict[str, Any]) -> dict[str, Any]:
        ok, message = runtime.run(
            runtime.plugins.load(str(body.get("name", ""))), timeout=180.0
        )
        return {"loaded": ok, "message": message}

    def plugin_unload(body: dict[str, Any]) -> dict[str, Any]:
        ok, message = runtime.run(runtime.plugins.unload(str(body.get("name", ""))))
        return {"unloaded": ok, "message": message}

    def workflows_list(_: dict[str, Any]) -> dict[str, Any]:
        return {"workflows": runtime.workflows.workflows(), "status": runtime.workflows.status()}

    def workflow_create(body: dict[str, Any]) -> dict[str, Any]:
        workflow, message = runtime.workflows.create(
            str(body.get("name", "")),
            list(body.get("steps", []) or []),
            description=str(body.get("description", "")),
            triggers=list(body.get("triggers", []) or []),
        )
        return {
            "created": workflow is not None,
            "message": message,
            "workflow": workflow.to_dict() if workflow else None,
        }

    def workflow_run(body: dict[str, Any]) -> dict[str, Any]:
        run = runtime.run(
            runtime.workflows.run(
                str(body.get("workflow_id", "")),
                input_text=str(body.get("input", "")),
            ),
            timeout=900.0,
        )
        return run.to_dict()

    def workflow_control(body: dict[str, Any]) -> dict[str, Any]:
        run_id = str(body.get("run_id", ""))
        action = str(body.get("action", "")).lower()
        handlers = {
            "pause": runtime.workflows.pause,
            "resume": runtime.workflows.resume,
            "cancel": runtime.workflows.cancel,
        }
        handler = handlers.get(action)
        if handler is None:
            return {"ok": False, "message": "Möglich sind: pause, resume, cancel."}
        return {"ok": handler(run_id), "action": action}

    def workflow_remove(body: dict[str, Any]) -> dict[str, Any]:
        ok, message = runtime.workflows.remove(str(body.get("workflow_id", "")))
        return {"removed": ok, "message": message}

    router.get("/tools", tools_list)
    router.get("/plugins", plugins_list)
    router.post("/plugins/load", plugin_load)
    router.post("/plugins/unload", plugin_unload)
    router.get("/workflows", workflows_list)
    router.post("/workflows/create", workflow_create)
    router.post("/workflows/run", workflow_run)
    router.post("/workflows/control", workflow_control)
    router.post("/workflows/remove", workflow_remove)

    # --- Bildverstehen ---------------------------------------------------------------

    def vision_status(_: dict[str, Any]) -> dict[str, Any]:
        return runtime.vision.status()

    def vision_read(body: dict[str, Any]) -> dict[str, Any]:
        result = runtime.run(
            runtime.vision.read_screen(monitor=int(body.get("monitor", 1))), timeout=180.0
        )
        return result.to_dict()

    def vision_describe(body: dict[str, Any]) -> dict[str, Any]:
        result = runtime.run(
            runtime.vision.describe_screen(
                str(body.get("question", "")), monitor=int(body.get("monitor", 1))
            ),
            timeout=300.0,
        )
        return result.to_dict()

    def vision_discard(_: dict[str, Any]) -> dict[str, Any]:
        return {"removed": runtime.vision.discard_all()}

    router.get("/vision", vision_status)
    router.post("/vision/read", vision_read)
    router.post("/vision/describe", vision_describe)
    router.post("/vision/discard", vision_discard)

    # --- Wissensbasis und Knowledge Graph ---------------------------------------------

    def knowledge_status(_: dict[str, Any]) -> dict[str, Any]:
        return {"status": runtime.knowledge.status(), "documents": runtime.knowledge.documents()}

    def knowledge_add(body: dict[str, Any]) -> dict[str, Any]:
        ok, message = runtime.knowledge.add_text(
            str(body.get("text", "")),
            title=str(body.get("title", "")),
            source=str(body.get("source", "")),
            citation=str(body.get("citation", "")),
        )
        return {"added": ok, "message": message}

    def knowledge_search(body: dict[str, Any]) -> dict[str, Any]:
        findings = runtime.knowledge.search(
            str(body.get("query", "")), limit=int(body.get("limit", 5))
        )
        return {"findings": [finding.to_dict() for finding in findings]}

    def knowledge_remove(body: dict[str, Any]) -> dict[str, Any]:
        ok, message = runtime.knowledge.remove(str(body.get("document_id", "")))
        return {"removed": ok, "message": message}

    def graph_status(_: dict[str, Any]) -> dict[str, Any]:
        return runtime.graph.status()

    def graph_nodes(body: dict[str, Any]) -> dict[str, Any]:
        return {"nodes": runtime.graph.nodes(body.get("type"))}

    def graph_connect(body: dict[str, Any]) -> dict[str, Any]:
        edge, message = runtime.graph.connect(
            str(body.get("source", "")),
            str(body.get("relation", "")),
            str(body.get("target", "")),
            source_type=str(body.get("source_type", "notiz")),
            target_type=str(body.get("target_type", "notiz")),
            evidence=str(body.get("evidence", "")),
        )
        return {"connected": edge is not None, "message": message}

    def graph_related(body: dict[str, Any]) -> dict[str, Any]:
        return {
            "related": runtime.graph.related(
                str(body.get("label", "")), depth=int(body.get("depth", 2))
            )
        }

    def graph_contradictions(_: dict[str, Any]) -> dict[str, Any]:
        return {"contradictions": runtime.graph.contradictions()}

    def graph_export(_: dict[str, Any]) -> dict[str, Any]:
        return {"path": str(runtime.graph.export())}

    router.get("/knowledge", knowledge_status)
    router.post("/knowledge/add", knowledge_add)
    router.post("/knowledge/search", knowledge_search)
    router.post("/knowledge/remove", knowledge_remove)
    router.get("/graph", graph_status)
    router.post("/graph/nodes", graph_nodes)
    router.post("/graph/connect", graph_connect)
    router.post("/graph/related", graph_related)
    router.get("/graph/contradictions", graph_contradictions)
    router.post("/graph/export", graph_export)

    # --- Lernen und Forschung -----------------------------------------------------------

    def flashcards_status(body: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": runtime.flashcards.status(),
            "due": [card.to_dict() for card in runtime.flashcards.due_cards(
                deck=str(body.get("deck", ""))
            )],
            "forecast": runtime.flashcards.forecast(),
        }

    def flashcard_add(body: dict[str, Any]) -> dict[str, Any]:
        card, message = runtime.flashcards.add(
            str(body.get("front", "")),
            str(body.get("back", "")),
            deck=str(body.get("deck", "allgemein")),
            tags=list(body.get("tags", []) or []),
        )
        return {"added": card is not None, "message": message}

    def flashcard_review(body: dict[str, Any]) -> dict[str, Any]:
        card, message = runtime.flashcards.review(
            str(body.get("card_id", "")), body.get("grade", "gut")
        )
        return {"reviewed": card is not None, "message": message}

    def study_status(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": runtime.study.status(),
            "plans": runtime.study.plans(),
            "today": runtime.study.today(),
        }

    def study_create(body: dict[str, Any]) -> dict[str, Any]:
        plan, message = runtime.study.create(
            str(body.get("title", "")),
            exam_date=str(body.get("exam_date", "")),
            hours_per_day=float(body.get("hours_per_day", 3.0)),
            topics=list(body.get("topics", []) or []),
        )
        return {"created": plan is not None, "message": message}

    def study_done(body: dict[str, Any]) -> dict[str, Any]:
        ok, message = runtime.study.mark_done(
            str(body.get("plan_id", "")), str(body.get("topic_id", ""))
        )
        return {"done": ok, "message": message}

    def research_question(body: dict[str, Any]) -> dict[str, Any]:
        return runtime.research.sharpen_question(str(body.get("question", "")))

    def research_thesis(body: dict[str, Any]) -> dict[str, Any]:
        review = runtime.research.review_thesis(str(body.get("thesis", "")))
        return {
            **review.to_dict(),
            "text": review.as_text(),
            "counterarguments": runtime.research.counterarguments(review.thesis),
        }

    def research_argument(body: dict[str, Any]) -> dict[str, Any]:
        return runtime.research.check_argument(str(body.get("text", "")))

    def research_outline(body: dict[str, Any]) -> dict[str, Any]:
        return runtime.research.outline_template(
            str(body.get("topic", "")), kind=str(body.get("kind", "hausarbeit"))
        )

    def research_source(body: dict[str, Any]) -> dict[str, Any]:
        assessment = runtime.sources.assess(
            str(body.get("description", "")),
            author=str(body.get("author", "")),
            year=str(body.get("year", "")),
            title=str(body.get("title", "")),
            publisher=str(body.get("publisher", "")),
        )
        return {**assessment.to_dict(), "text": assessment.as_text()}

    router.post("/flashcards", flashcards_status)
    router.post("/flashcards/add", flashcard_add)
    router.post("/flashcards/review", flashcard_review)
    router.get("/study", study_status)
    router.post("/study/create", study_create)
    router.post("/study/done", study_done)
    router.post("/research/question", research_question)
    router.post("/research/thesis", research_thesis)
    router.post("/research/argument", research_argument)
    router.post("/research/outline", research_outline)
    router.post("/research/source", research_source)

    # --- Präsenz, Heatmap, Fenster ------------------------------------------------------

    def presence_status(_: dict[str, Any]) -> dict[str, Any]:
        return runtime.presence.snapshot()

    def presence_suppress(body: dict[str, Any]) -> dict[str, Any]:
        runtime.presence.suppress(float(body.get("minutes", 60)))
        return {"suppressed": True}

    def heatmap_status(_: dict[str, Any]) -> dict[str, Any]:
        return runtime.heatmap.status()

    def heatmap_record(body: dict[str, Any]) -> dict[str, Any]:
        kind = str(body.get("kind", "mouse")).lower()
        arguments = {
            "screen_width": float(body.get("screen_width", 1920)),
            "screen_height": float(body.get("screen_height", 1080)),
            "monitor": int(body.get("monitor", 0)),
        }
        x = float(body.get("x", 0))
        y = float(body.get("y", 0))

        if kind == "click":
            runtime.heatmap.record_click(x, y, **arguments)
        elif kind == "typing":
            runtime.heatmap.record_typing(x, y, **arguments)
        elif kind == "orb_moved_away":
            runtime.heatmap.record_orb_moved_away(x, y, **arguments)
        else:
            runtime.heatmap.record_mouse(x, y, **arguments)

        return {"recorded": True}

    def heatmap_quiet(body: dict[str, Any]) -> dict[str, Any]:
        return {
            "spots": runtime.heatmap.quiet_spots(
                screen_width=float(body.get("screen_width", 1920)),
                screen_height=float(body.get("screen_height", 1080)),
                monitor=int(body.get("monitor", 0)),
            ),
            "grid": runtime.heatmap.grid_snapshot(int(body.get("monitor", 0))),
        }

    def heatmap_clear(_: dict[str, Any]) -> dict[str, Any]:
        return {"cleared": runtime.heatmap.clear()}

    def windows_list(_: dict[str, Any]) -> dict[str, Any]:
        # Welches Fenster gerade vorn ist, gehört mit in die Antwort.
        #
        # Die Oberfläche braucht es, um den Orb dorthin zu setzen, wo
        # gearbeitet wird – daneben, nicht darauf. Ohne diese Angabe müsste
        # sie ein zweites Mal fragen, und zwischen beiden Fragen könnte
        # sich der Vordergrund längst geändert haben.
        active = runtime.windows.active_window()
        return {
            "windows": [window.to_dict() for window in runtime.windows.list_windows()],
            "active_handle": active.handle if active is not None else 0,
            "status": runtime.windows.status(),
        }

    def window_focus(body: dict[str, Any]) -> dict[str, Any]:
        matches = runtime.windows.find(str(body.get("title", "")))
        if not matches:
            return {"ok": False, "message": "Kein passendes Fenster gefunden."}
        ok, message = runtime.windows.focus(matches[0])
        return {"ok": ok, "message": message, "window": matches[0].to_dict()}

    def window_tile(body: dict[str, Any]) -> dict[str, Any]:
        return runtime.windows.tile(list(body.get("titles", []) or []))

    router.get("/presence", presence_status)
    router.post("/presence/suppress", presence_suppress)
    router.get("/heatmap", heatmap_status)
    router.post("/heatmap/record", heatmap_record)
    router.post("/heatmap/quiet", heatmap_quiet)
    router.post("/heatmap/clear", heatmap_clear)
    router.get("/windows", windows_list)
    router.post("/windows/focus", window_focus)
    router.post("/windows/tile", window_tile)

    return router


def create_server(runtime: Runtime) -> LocalApiServer:
    """Erstellt den lokalen API-Server und verbindet ihn mit dem Event Bus.

    Jedes Event des Event Bus wird automatisch an alle verbundenen
    Frontend-Clients weitergereicht.
    """

    config = get_config()
    backend_config = config.section("backend")

    broker = SseBroker()
    router = build_router(runtime)

    async def forward(event: Event) -> None:
        broker.broadcast(event.name, event.payload)

    runtime.event_bus.subscribe(WILDCARD, forward)

    server = LocalApiServer(
        host=str(backend_config.get("host", "127.0.0.1")),
        port=int(backend_config.get("port", 8756)),
        router=router,
        broker=broker,
        sse_path=str(backend_config.get("events_path", "/events")),
    )
    return server
