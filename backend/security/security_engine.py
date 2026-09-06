"""Security Engine – die zentrale Stelle für alle heiklen Aktionen.

Jedes Modul, das mehr tun will als antworten, fragt hier. Die Engine prüft
in dieser Reihenfolge:

1. Ist die Berechtigung überhaupt bekannt? Unbekanntes wird verweigert.
2. Ist sie in ``config.yaml`` grundsätzlich gesperrt? Dann wird auch mit
   Zustimmung nichts getan.
3. Ist sie unbedenklich? Dann darf sie ohne Frage ausgeführt werden.
4. Liegt eine gemerkte Zustimmung vor? Dann gilt sie.
5. Sonst wird gefragt – und das Ergebnis protokolliert.

Der Sinn der Bündelung: Es gibt genau einen Ort, an dem entschieden wird.
Wer die Sicherheitsregeln nachlesen will, muss nur diese Datei verstehen,
und wer sie ändern will, kann es nicht versehentlich an einer Stelle
vergessen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.config import get_config
from backend.events.event_bus import EventBus
from backend.security.audit_log import AuditEntry, AuditLog
from backend.security.consent import ConsentManager
from backend.security.path_guard import PathDecision, PathGuard
from backend.security.permissions import (
    KNOWN_PERMISSIONS,
    Permission,
    RiskLevel,
    describe,
    get_permission,
)
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class SecurityDecision:
    """Das Ergebnis einer Sicherheitsprüfung."""

    allowed: bool
    #: Warum – im Klartext, geeignet zur direkten Ausgabe an den Benutzer.
    reason: str = ""
    #: Ob die Erlaubnis aus einer gemerkten Zustimmung stammt.
    from_memory: bool = False

    def __bool__(self) -> bool:
        return self.allowed


class SecurityEngine:
    """Bündelt Berechtigungen, Zustimmung, Pfadschutz und Protokoll."""

    def __init__(self, event_bus: EventBus) -> None:
        config = get_config()

        self.audit = AuditLog(
            max_entries=int(config.get("security.audit_max_entries", 5000)),
        )
        self.consent = ConsentManager(
            event_bus,
            timeout_seconds=float(config.get("security.consent_timeout_seconds", 120)),
        )
        #: Der Betriebsmodus der Sicherheitsschicht.
        #:
        #: ``geschuetzt``  – die Vorgabe: fragen, sperren, protokollieren.
        #: ``offen``       – alles erlaubt, nichts gefragt.
        #:
        #: Der offene Modus ist eine ausdrückliche Entscheidung des
        #: Benutzers und keine Bequemlichkeit. Er hebt die Rückfragen auf,
        #: die Pfadsperren und die Liste des Unerlaubten. Was bleibt, ist
        #: das Prüfprotokoll – es kostet nichts, stört nicht und ist das
        #: Einzige, was hinterher noch sagen kann, was geschehen ist.
        self.mode = str(config.get("security.mode", "geschuetzt")).strip().lower()

        self.paths = PathGuard(
            config.get("desktop.file_search_roots", []) or [],
            unrestricted=self.is_open,
        )

        #: Berechtigungen, die auch mit Zustimmung niemals gewährt werden.
        self._blocked: set[str] = (
            set()
            if self.is_open
            else {
                str(name).strip().lower()
                for name in (config.get("security.never_allow", []) or [])
            }
        )

        #: Berechtigungen, die ohne Frage gelten, weil der Benutzer sie in
        #: der Konfiguration vorab erteilt hat.
        #:
        #: Kritische Berechtigungen sind hiervon ausgenommen, und zwar
        #: bewusst. Eine Zeile in der config.yaml darf nicht aufheben, was
        #: die Selbstverbesserung dem Benutzer zusagt: uebernommen wird nur,
        #: was er antippt. ``permissions.py`` verbietet fuer kritische Rechte
        #: bereits das Merken einer Zustimmung; eine Vorabfreigabe waere
        #: dasselbe in dauerhaft. Was hier abgelehnt wird, steht im
        #: Protokoll und in ``status()`` - stillschweigend verschwindet
        #: nichts.
        gewuenscht_vorab = {
            str(name).strip().lower()
            for name in (config.get("security.pre_approved", []) or [])
        }
        self._preapproved: set[str] = set()
        #: Vorabfreigaben, die wegen ihrer Einstufung nicht gelten.
        self._preapproved_rejected: set[str] = set()
        for _name in sorted(gewuenscht_vorab):
            _permission = get_permission(_name)
            if _permission is not None and _permission.risk is RiskLevel.CRITICAL:
                self._preapproved_rejected.add(_name)
                continue
            self._preapproved.add(_name)

        if self._preapproved_rejected:
            logger.warning(
                "Vorabfreigabe fuer kritische Berechtigungen ignoriert: %s. "
                "Kritische Aktionen werden weiterhin jedes Mal einzeln "
                "erfragt. Wer sie wirklich ohne Rueckfrage will, muss dafuer "
                "'security.mode: offen' setzen - und weiss dann, was er tut.",
                ", ".join(sorted(self._preapproved_rejected)),
            )

        if self.is_open:
            # Unübersehbar, und zwar mit Absicht.
            #
            # Der offene Modus hebt ALLES auf: Rückfragen, Pfadsperren, die
            # Liste des Unerlaubten - auch für kritische Rechte wie
            # modify_own_code. Er ist eine legitime Entscheidung des
            # Benutzers und wird deshalb nicht heimlich geändert. Aber er
            # darf nicht wie eine Nebensächlichkeit im Protokoll stehen,
            # sonst weiss nach zwei Wochen niemand mehr, dass er gilt.
            for zeile in (
                "=" * 72,
                "ACHTUNG: Die Sicherheitsschicht laeuft im OFFENEN Modus.",
                f"  Alle {len(KNOWN_PERMISSIONS)} Berechtigungen gelten ohne "
                "Rueckfrage - auch die kritischen",
                "  (system_commands, delete_files, send_email, modify_own_code).",
                "  Es gibt keine Pfadsperren und keine Liste des Unerlaubten.",
                "  Geaendert wird das mit 'security.mode: geschuetzt' in der "
                "config.yaml.",
                "  Was geschieht, steht weiterhin im Pruefprotokoll.",
                "=" * 72,
            ):
                logger.error("%s", zeile)
        else:
            logger.info(
                "Sicherheitsschicht bereit: %d Berechtigungen bekannt, %d gesperrt, "
                "%d Ordner freigegeben.",
                len(KNOWN_PERMISSIONS),
                len(self._blocked),
                len(self.paths.roots),
            )

    @property
    def is_open(self) -> bool:
        """Ob alles ohne Rückfrage erlaubt ist."""

        return self.mode in {"offen", "open", "unrestricted", "alles"}

    # --- Hauptprüfung -------------------------------------------------------------

    async def require(
        self,
        actor: str,
        permission_name: str,
        detail: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> SecurityDecision:
        """Verlangt eine Berechtigung und fragt bei Bedarf den Benutzer.

        Args:
            actor: Wer fragt – Modulname, Skill, Plugin oder Agent.
            permission_name: Name der Berechtigung.
            detail: Was genau geschehen soll, im Klartext.
            context: Zusatzangaben für Anzeige und Protokoll.

        Returns:
            Die Entscheidung. Bei Ablehnung enthält ``reason`` eine für den
            Benutzer verständliche Begründung.
        """

        permission = get_permission(permission_name)

        if self.is_open:
            # Im offenen Modus wird nichts gefragt und nichts gesperrt –
            # auch nicht bei einer unbekannten Berechtigung. Aufgeschrieben
            # wird trotzdem alles: Wer im Nachhinein wissen will, was der
            # Orb getan hat, findet es hier und sonst nirgends.
            self.audit.record(
                AuditEntry(
                    event="permission.granted",
                    actor=actor,
                    permission=permission.name if permission else permission_name,
                    detail=detail,
                    allowed=True,
                    context={**(context or {}), "modus": "offen"},
                )
            )
            return SecurityDecision(True, "Offener Modus – ohne Rückfrage erlaubt.")

        if permission is None:
            return self._deny(
                actor,
                permission_name,
                detail,
                f"'{permission_name}' ist keine bekannte Berechtigung. "
                "Unbekannte Berechtigungen werden grundsätzlich verweigert.",
                context,
            )

        if permission.name in self._blocked:
            return self._deny(
                actor,
                permission.name,
                detail,
                f"'{permission.description}' ist in config.yaml unter "
                "'security.never_allow' gesperrt. Auch eine Zustimmung ändert "
                "daran nichts.",
                context,
            )

        # Die zweite Haelfte dieser Bedingung schliesst kritische Rechte
        # noch einmal ausdruecklich aus. Die Liste ist beim Aufbau schon
        # bereinigt; hier steht die Pruefung trotzdem, weil diese Zeile
        # darueber entscheidet, ob ueberhaupt gefragt wird.
        if permission.risk is RiskLevel.SAFE or (
            permission.name in self._preapproved
            and permission.risk is not RiskLevel.CRITICAL
        ):
            self.audit.record(
                AuditEntry(
                    event="permission.granted",
                    actor=actor,
                    permission=permission.name,
                    detail=detail,
                    allowed=True,
                    context=context or {},
                )
            )
            return SecurityDecision(True, "Unbedenklich")

        decision = await self.consent.request(
            actor, permission, detail, context=context
        )

        self.audit.record(
            AuditEntry(
                event="consent.granted" if decision.granted else "consent.denied",
                actor=actor,
                permission=permission.name,
                detail=detail,
                allowed=decision.granted,
                context={**(context or {}), "remembered": decision.remembered},
            )
        )

        return SecurityDecision(
            allowed=decision.granted,
            reason=decision.reason,
            from_memory=decision.remembered,
        )

    def _deny(
        self,
        actor: str,
        permission_name: str,
        detail: str,
        reason: str,
        context: dict[str, Any] | None,
    ) -> SecurityDecision:
        self.audit.record(
            AuditEntry(
                event="permission.denied",
                actor=actor,
                permission=permission_name,
                detail=detail,
                allowed=False,
                context=context or {},
            )
        )
        logger.warning("Verweigert: %s wollte '%s' – %s", actor, permission_name, reason)
        return SecurityDecision(False, reason)

    # --- Pfadprüfungen -------------------------------------------------------------

    async def require_read_path(self, actor: str, path: str) -> tuple[SecurityDecision, PathDecision]:
        """Prüft Berechtigung und Pfad für einen Lesezugriff."""

        path_decision = self.paths.check_read(path)
        if not path_decision.allowed:
            return (
                self._deny(actor, "read_files", f"Datei lesen: {path}", path_decision.reason, None),
                path_decision,
            )

        decision = await self.require(
            actor, "read_files", f"Die Datei '{path_decision.path}' lesen"
        )
        return decision, path_decision

    async def require_write_path(self, actor: str, path: str) -> tuple[SecurityDecision, PathDecision]:
        """Prüft Berechtigung und Pfad für einen Schreibzugriff."""

        path_decision = self.paths.check_write(path)
        if not path_decision.allowed:
            return (
                self._deny(
                    actor, "write_files", f"Datei schreiben: {path}", path_decision.reason, None
                ),
                path_decision,
            )

        decision = await self.require(
            actor, "write_files", f"Die Datei '{path_decision.path}' schreiben"
        )
        return decision, path_decision

    # --- Protokollierung ausgeführter Aktionen ---------------------------------------

    def record_action(
        self,
        actor: str,
        permission_name: str,
        detail: str,
        *,
        succeeded: bool = True,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Hält fest, dass eine erlaubte Aktion tatsächlich ausgeführt wurde."""

        self.audit.record(
            AuditEntry(
                event="action.executed" if succeeded else "action.failed",
                actor=actor,
                permission=permission_name,
                detail=detail,
                allowed=succeeded,
                context=context or {},
            )
        )

    # --- Auskunft --------------------------------------------------------------------

    def catalog(self) -> list[dict[str, Any]]:
        """Alle bekannten Berechtigungen mit Beschreibung und Einstufung."""

        entries = describe(sorted(KNOWN_PERMISSIONS))
        for entry in entries:
            name = str(entry.get("name", ""))
            entry["blocked"] = name in self._blocked
            entry["pre_approved"] = name in self._preapproved
        return entries

    def evaluate_manifest(self, requested: list[str]) -> dict[str, Any]:
        """Bewertet die Berechtigungsliste eines Skills oder Plugins.

        Wird vor der Installation angezeigt, damit der Benutzer sieht, worauf
        er sich einlässt.
        """

        described = describe(requested)
        unknown = [entry["name"] for entry in described if entry.get("unknown")]
        blocked = [
            entry["name"] for entry in described if str(entry["name"]) in self._blocked
        ]
        return {
            "permissions": described,
            "unknown": unknown,
            "blocked": blocked,
            "installable": not unknown and not blocked,
            "summary": self._manifest_summary(described, unknown, blocked),
        }

    @staticmethod
    def _manifest_summary(
        described: list[dict[str, Any]], unknown: list[str], blocked: list[str]
    ) -> str:
        if unknown:
            return (
                "Es werden unbekannte Berechtigungen verlangt: "
                + ", ".join(unknown)
                + ". Die Installation wird abgelehnt."
            )
        if blocked:
            return (
                "Es werden gesperrte Berechtigungen verlangt: "
                + ", ".join(blocked)
                + ". Die Installation wird abgelehnt."
            )
        critical = [
            entry["name"]
            for entry in described
            if entry.get("risk") == RiskLevel.CRITICAL.value
        ]
        if critical:
            return (
                "Achtung: Es werden kritische Berechtigungen verlangt ("
                + ", ".join(critical)
                + "). Jede einzelne Ausführung muss bestätigt werden."
            )
        if not described:
            return "Es werden keine besonderen Berechtigungen verlangt."
        return f"Es werden {len(described)} Berechtigungen verlangt, keine davon kritisch."

    def status(self) -> dict[str, Any]:
        """Gesamtstatus der Sicherheitsschicht."""

        return {
            "modus": self.mode,
            "offener_modus": self.is_open,
            "known_permissions": len(KNOWN_PERMISSIONS),
            "never_allow": sorted(self._blocked),
            "pre_approved": sorted(self._preapproved),
            "pre_approved_rejected": sorted(self._preapproved_rejected),
            "consent": self.consent.status(),
            "audit": self.audit.summary(),
            "paths": self.paths.status(),
        }


def permission_names() -> list[str]:
    """Alle bekannten Berechtigungsnamen."""

    return sorted(KNOWN_PERMISSIONS)


__all__ = [
    "SecurityEngine",
    "SecurityDecision",
    "Permission",
    "RiskLevel",
    "permission_names",
]
