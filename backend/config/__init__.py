"""Konfigurationsschicht von AI-Orb.

Stellt den :class:`~backend.config.config_loader.ConfigLoader` bereit, über
den ausschließlich auf die Werte aus ``config.yaml`` zugegriffen werden darf.
Kein anderes Modul liest ``config.yaml`` direkt.

Zugangsdaten stehen niemals in ``config.yaml``, sondern in der Datei
``.env``. Diese wird über
:func:`~backend.config.env_loader.load_env_file` eingelesen.
"""

from backend.config.config_loader import ConfigLoader, get_config
from backend.config.env_loader import load_env_file, parse_env_text

__all__ = ["ConfigLoader", "get_config", "load_env_file", "parse_env_text"]
