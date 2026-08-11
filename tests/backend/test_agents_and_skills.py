"""Tests für das Agenten-Team und das Skill-System."""

from __future__ import annotations

import pytest

from backend.agents.agent_metrics import AgentMetrics
from backend.agents.agent_registry import AgentRegistry
from backend.agents.agent_router import AgentRouter
from backend.agents.base_agent import AgentResult, AgentTask, BaseAgent
from backend.agents.capability_registry import CapabilityRegistry
from backend.agents.result_merger import ResultMerger
from backend.cognitive.orchestrator import Distribution, SubTask
from backend.skills.skill_permissions import SkillPermissions
from backend.skills.skill_registry import SkillManifest
from backend.skills.skill_validator import SkillValidator


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.utils.store.get_data_dir", lambda: tmp_path)
    yield tmp_path


class _EchoAgent(BaseAgent):
    """Ein einfacher Testagent, der die Eingabe zurückgibt."""

    name = "echo"
    description = "Testagent"
    capabilities = ("echo",)
    requires_llm = False

    async def handle(self, task: AgentTask) -> AgentResult:
        return AgentResult(agent=self.name, response=f"echo: {task.text}")


class _FailingAgent(BaseAgent):
    """Ein Agent, der immer fehlschlägt."""

    name = "kaputt"
    description = "Schlägt immer fehl"
    capabilities = ("kaputt",)
    requires_llm = False

    async def handle(self, task: AgentTask) -> AgentResult:
        raise RuntimeError("Absicht")


async def test_agent_failure_does_not_crash_the_orb():
    """Ein fehlerhafter Agent darf den Orb nicht zum Absturz bringen."""

    agent = _FailingAgent()
    result = await agent.run(AgentTask(text="test"))

    assert result.success is False
    assert result.error


def test_registry_registers_and_lists_agents():
    registry = AgentRegistry()
    registry.register(_EchoAgent())

    assert "echo" in registry.names()
    assert registry.get("echo") is not None


async def test_registry_self_test_marks_agent_as_tested():
    registry = AgentRegistry()
    registry.register(_EchoAgent())

    report = await registry.self_test("echo")

    assert report["passed"] is True
    assert registry.is_tested("echo") is True


def test_capability_registry_tracks_permissions():
    capabilities = CapabilityRegistry()
    agent = _EchoAgent()
    capabilities.register_agent(agent, ["file_read"])
    capabilities.grant("echo", "file_read")

    assert capabilities.has("echo") is True
    assert capabilities.is_allowed("echo", "file_read") is True
    assert capabilities.is_allowed("echo", "system_commands") is False


def test_unknown_permission_is_rejected():
    capabilities = CapabilityRegistry()

    assert capabilities.grant("echo", "weltherrschaft") is False


def test_router_runs_desktop_agent_alone():
    """Desktop-Aktionen verändern den Systemzustand und laufen daher allein."""

    router = AgentRouter(CapabilityRegistry())
    distribution = Distribution(
        subtasks=[
            SubTask(text="Frage", engine="history", order=0),
            SubTask(text="Öffne", engine="desktop", order=1),
        ],
        engines=["history", "desktop"],
    )

    plan = router.plan(distribution, available_agents=["history", "desktop"])

    assert plan.stages[-1] == ["desktop"]
    assert plan.reason


def test_router_puts_memory_first():
    router = AgentRouter(CapabilityRegistry())
    distribution = Distribution(engines=["history", "memory"])

    plan = router.plan(distribution, available_agents=["history", "memory"])

    assert plan.stages[0] == ["memory"]


def test_merger_removes_duplicates():
    merger = ResultMerger()
    results = [
        AgentResult(agent="history", response="Der Investiturstreit endete 1122.", order=0),
        AgentResult(agent="conversation", response="Der Investiturstreit endete 1122.", order=0),
    ]

    merged = merger.merge(results)

    assert merged.text.count("1122") == 1
    assert len(merged.agents_used) == 1


def test_merger_reports_partial_answer():
    """Fällt ein Agent aus, gibt es eine Teilantwort – keinen stillen Fehler."""

    merger = ResultMerger()
    results = [
        AgentResult(agent="history", response="Eine Antwort.", order=0),
        AgentResult(agent="research", success=False, error="nicht erreichbar", order=1),
    ]

    merged = merger.merge(results)

    assert merged.partial is True
    assert "research" in merged.text
    assert merged.failed_agents


def test_merger_reports_total_failure_clearly():
    merger = ResultMerger()
    results = [AgentResult(agent="history", success=False, error="Zeitlimit", order=0)]

    merged = merger.merge(results)

    assert "Zeitlimit" in merged.text


def test_metrics_track_success_rate():
    metrics = AgentMetrics()
    metrics.record("echo", success=True, duration=0.1)
    metrics.record("echo", success=False, duration=0.2)

    stats = metrics.get("echo")

    assert stats is not None
    assert stats.invocations == 2
    assert stats.success_rate == 0.5


# --- Skill-System ------------------------------------------------------------


def _write_skill(directory, *, permissions=None, with_tests=True, dangerous=False):
    directory.mkdir(parents=True, exist_ok=True)
    source = "def handle(payload):\n    return {'success': True}\n"
    if dangerous:
        source = "def handle(payload):\n    return eval(payload['code'])\n"
    (directory / "skill.py").write_text(source, encoding="utf-8")
    if with_tests:
        (directory / "test_skill.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (directory / "README.md").write_text("# Testskill\n", encoding="utf-8")
    return SkillManifest(
        name="testskill",
        version="1.0.0",
        description="Ein Testskill.",
        permissions=list(permissions or []),
        capabilities=["testen"],
    )


def test_validator_accepts_valid_skill(tmp_path):
    directory = tmp_path / "testskill"
    manifest = _write_skill(directory)

    report = SkillValidator().validate(manifest, directory)

    assert report.valid is True
    assert report.has_tests is True


def test_validator_rejects_unknown_permission(tmp_path):
    directory = tmp_path / "testskill"
    manifest = _write_skill(directory, permissions=["weltherrschaft"])

    report = SkillValidator().validate(manifest, directory)

    assert report.valid is False


def test_validator_flags_dangerous_code(tmp_path):
    directory = tmp_path / "testskill"
    manifest = _write_skill(directory, dangerous=True)

    report = SkillValidator().validate(manifest, directory)

    assert report.security_findings


def test_validator_warns_about_missing_tests(tmp_path):
    directory = tmp_path / "testskill"
    manifest = _write_skill(directory, with_tests=False)

    report = SkillValidator().validate(manifest, directory)

    assert report.has_tests is False
    assert any("Tests" in warning for warning in report.warnings)


def test_permission_request_is_understandable():
    permissions = SkillPermissions()

    request = permissions.build_request("zotero", ["file_read", "database"])

    assert request.needs_confirmation is True
    assert "Dateien lesen" in request.describe()
