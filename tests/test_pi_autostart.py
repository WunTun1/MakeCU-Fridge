from pi_node import run


def test_autostart_on_writes_a_terminal_entry_and_off_removes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "AUTOSTART_FILE", tmp_path / "autostart" / "refridge.desktop")
    monkeypatch.setattr(run.shutil, "which", lambda name: "/usr/bin/lxterminal" if name == "lxterminal" else None)
    run.set_autostart(True)
    entry = run.AUTOSTART_FILE.read_text()
    assert "Type=Application" in entry
    assert "Exec=/usr/bin/lxterminal" in entry and "run.py" in entry  # in a terminal, so Ctrl+C reaches it
    assert "Press Enter to close" in entry  # the window stays to show why it stopped
    run.set_autostart(False)
    assert not run.AUTOSTART_FILE.exists()
