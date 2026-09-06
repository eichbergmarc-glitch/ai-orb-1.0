"""Der zweite Orb darf nie bis zu Mikrofon oder Sprachausgabe gelangen."""

import backend.main as main


def test_zweiter_start_endet_vor_launcher(monkeypatch):
    gestartet = []
    monkeypatch.setattr(main, "_acquire_single_instance", lambda: False)
    monkeypatch.setattr(main, "run_with_launcher", lambda: gestartet.append(True) or 0)

    assert main.main(["--launcher"]) == 0
    assert gestartet == []


def test_prueflauf_braucht_keine_einzelinstanz(monkeypatch):
    monkeypatch.setattr(main, "run_check", lambda: 7)
    monkeypatch.setattr(
        main, "_acquire_single_instance",
        lambda: (_ for _ in ()).throw(AssertionError("Mutex beim Check")),
    )

    assert main.main(["--check"]) == 7
