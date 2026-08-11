"""Sicherheitsschicht von AI-Orb (v2 Phase 8).

Hier laufen alle heiklen Aktionen zusammen. Kein anderes Modul entscheidet
selbst, ob es etwas darf – es fragt die :class:`SecurityEngine`.

Die Bestandteile:

* :mod:`backend.security.permissions` – welche Berechtigungen es gibt und
  wie schwer sie wiegen.
* :mod:`backend.security.consent` – wie der Benutzer gefragt wird und was
  gemerkt werden darf.
* :mod:`backend.security.path_guard` – welche Ordner überhaupt berührt
  werden dürfen.
* :mod:`backend.security.audit_log` – was tatsächlich geschehen ist.
* :mod:`backend.security.security_engine` – die Fassade, die alles bündelt.
"""

from backend.security.audit_log import AuditEntry, AuditLog
from backend.security.consent import (
    CONSENT_REQUESTED,
    CONSENT_RESOLVED,
    CONSENT_REVOKED,
    ConsentDecision,
    ConsentManager,
    ConsentRequest,
)
from backend.security.path_guard import PathDecision, PathGuard
from backend.security.permissions import (
    KNOWN_PERMISSIONS,
    Permission,
    RiskLevel,
    describe,
    get_permission,
    highest_risk,
)
from backend.security.security_engine import SecurityDecision, SecurityEngine, permission_names

__all__ = [
    "AuditEntry",
    "AuditLog",
    "CONSENT_REQUESTED",
    "CONSENT_RESOLVED",
    "CONSENT_REVOKED",
    "ConsentDecision",
    "ConsentManager",
    "ConsentRequest",
    "KNOWN_PERMISSIONS",
    "PathDecision",
    "PathGuard",
    "Permission",
    "RiskLevel",
    "SecurityDecision",
    "SecurityEngine",
    "describe",
    "get_permission",
    "highest_risk",
    "permission_names",
]
