import ipaddress

from pi_node import link


def test_already_on_the_cable_changes_nothing(monkeypatch):
    monkeypatch.setattr(link, "local_ipv4", lambda: [ipaddress.ip_interface("192.168.50.2/24")])
    calls = []
    monkeypatch.setattr(link.subprocess, "run", lambda *a, **k: calls.append(a))
    assert link.ensure_link(quiet=True)
    assert calls == []  # no nmcli, no sudo


def test_first_time_creates_the_profile_set_to_come_up_at_boot(monkeypatch):
    addresses = [[], [], [ipaddress.ip_interface("192.168.50.2/24")]]
    monkeypatch.setattr(link, "local_ipv4", lambda: addresses.pop(0) if len(addresses) > 1 else addresses[0])
    monkeypatch.setattr(link.shutil, "which", lambda name: "/usr/bin/nmcli")
    commands = []

    class Done:
        returncode = 0
        stdout = "Wired connection 1\n"

    def run(cmd, **kwargs):
        commands.append(cmd)
        return Done()

    monkeypatch.setattr(link.subprocess, "run", run)
    monkeypatch.setattr(link.time, "sleep", lambda s: None)
    assert link.ensure_link(quiet=True)
    add = next(c for c in commands if c[:3] == ["nmcli", "con", "add"])
    assert "192.168.50.2/24" in add and "connection.autoconnect" in add
    assert ["nmcli", "con", "up", "direct"] in commands


def test_pull_explains_how_to_start_the_laptops_git_server(monkeypatch, capsys):
    monkeypatch.setattr(link, "port_open", lambda host, port, timeout=2: False)
    assert link.pull() is False
    assert "git daemon" in capsys.readouterr().out
