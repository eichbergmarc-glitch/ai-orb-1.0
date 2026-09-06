"""Biometrie darf die Windows-Anmeldung nicht in den Orb verlagern."""

from backend.config import get_config


def test_windows_hello_bleibt_allein_fuer_die_rechnerentsperrung_zustaendig():
    cfg = get_config()

    assert cfg.get("security.biometric_identity.provider") == "windows_hello"
    assert cfg.get("security.biometric_identity.windows_unlock") == "os_managed"
    assert cfg.get("security.biometric_identity.private_face_database") is False
    assert cfg.get("security.biometric_identity.password_injection") is False
