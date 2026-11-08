"""Just the cable link to the laptop: bring it up, check the laptop answers, and optionally
update the code over it — without starting the sensors or the fridge screen.

    python3 ~/MakeCU-Fridge/pi_node/link.py          # link up + check the laptop
    python3 ~/MakeCU-Fridge/pi_node/link.py --pull   # ...then git pull from the laptop

Standard library only, so plain python3 runs it even before the .venv exists.

The laptop's end of the cable is 192.168.50.1 (kiosk/HYBRID_SETUP.md, option A). For
--pull the laptop serves the repo read-only over git; on the laptop, from the folder
that contains MakeCU-Fridge:
    git daemon --reuseaddr --export-all --base-path=. --listen=192.168.50.1 MakeCU-Fridge

The first time, this creates the Pi's `direct` NetworkManager profile and sets it to come
up by itself at boot. To plug the Pi into a router instead: sudo nmcli con down direct
(and `sudo nmcli con up direct` to come back).
"""
from __future__ import annotations

import argparse
import ipaddress
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CONNECTION = "direct"                       # the NetworkManager profile for the cable
NETWORK = ipaddress.ip_network("192.168.50.0/24")
PI_ADDRESS = "192.168.50.2/24"
LAPTOP = "192.168.50.1"
BACKEND_PORT = 8000
GIT_PORT = 9418
GIT_REMOTE = "laptop"
GIT_URL = f"git://{LAPTOP}/MakeCU-Fridge"


def say(msg: str) -> None:
    print(f"[refridge] {msg}", flush=True)


def local_ipv4() -> list[ipaddress.IPv4Interface]:
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [ipaddress.ip_interface(line.split()[3]) for line in out.splitlines() if len(line.split()) > 3]


def on_link() -> bool:
    return any(i.ip in NETWORK for i in local_ipv4())


def _nmcli(cmd: list[str]) -> bool:
    """Run an nmcli command; if this user isn't allowed to, try once with sudo (asks for the password)."""
    if subprocess.run(cmd, capture_output=True).returncode == 0:
        return True
    return subprocess.run(["sudo", *cmd]).returncode == 0


def ensure_link(quiet: bool = False) -> bool:
    """The Pi's address on the cable (192.168.50.2), creating the profile the first time."""
    if on_link():
        if not quiet:
            say("Cable link is up (this Pi is 192.168.50.2).")
        return True
    if not shutil.which("nmcli"):
        say("nmcli not found — this needs Raspberry Pi OS (NetworkManager).")
        return False
    say("Bringing up the cable link (192.168.50.2)...")
    profiles = subprocess.run(["nmcli", "-t", "-f", "NAME", "con", "show"], capture_output=True, text=True).stdout.split()
    boot = ["connection.autoconnect", "yes", "connection.autoconnect-priority", "10"]  # beats the default DHCP profile
    if CONNECTION not in profiles:
        if not _nmcli(["nmcli", "con", "add", "type", "ethernet", "ifname", "eth0", "con-name", CONNECTION,
                       "ipv4.method", "manual", "ipv4.addresses", PI_ADDRESS, *boot]):
            say(f"Couldn't create the link. Manually: sudo nmcli con add type ethernet ifname eth0 "
                f"con-name {CONNECTION} ipv4.method manual ipv4.addresses {PI_ADDRESS}")
            return False
    else:
        _nmcli(["nmcli", "con", "mod", CONNECTION, *boot])
    if not _nmcli(["nmcli", "con", "up", CONNECTION]):
        say("Couldn't bring the link up. Is the cable plugged into the Pi's Ethernet port?")
        return False
    for _ in range(10):
        if on_link():
            say("Cable link is up (this Pi is 192.168.50.2).")
            return True
        time.sleep(0.5)
    return on_link()


def port_open(host: str, port: int, timeout: float = 2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def laptop_answers() -> bool:
    return subprocess.run(["ping", "-c", "1", "-W", "2", LAPTOP], capture_output=True).returncode == 0


def pull() -> bool:
    if not port_open(LAPTOP, GIT_PORT):
        say("The laptop isn't serving the code. On the laptop, from the folder that contains MakeCU-Fridge:")
        say(f"  git daemon --reuseaddr --export-all --base-path=. --listen={LAPTOP} MakeCU-Fridge")
        return False
    remotes = subprocess.run(["git", "remote"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    if GIT_REMOTE not in remotes:
        subprocess.run(["git", "remote", "add", GIT_REMOTE, GIT_URL], cwd=ROOT, check=True)
    say(f"Pulling from the laptop ({GIT_URL})...")
    if subprocess.run(["git", "pull", GIT_REMOTE, "main"], cwd=ROOT).returncode != 0:
        say("Pull failed. If it says local changes would be overwritten (files copied over by hand),")
        say("  run: git checkout -- pi_node/   and try again.")
        return False
    head = subprocess.run(["git", "log", "--oneline", "-1"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    say(f"Up to date: {head}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pull", action="store_true", help="also update the code from the laptop")
    args = parser.parse_args()

    if not ensure_link():
        sys.exit(1)
    if not laptop_answers():
        say(f"No answer from the laptop at {LAPTOP}. On the laptop, its cable adapter needs that address:")
        say(f'  New-NetIPAddress -InterfaceAlias "Ethernet 2" -IPAddress {LAPTOP} -PrefixLength 24   (admin PowerShell)')
        sys.exit(1)
    say(f"Laptop answers at {LAPTOP}.")
    say("Backend: running." if port_open(LAPTOP, BACKEND_PORT) else
        "Backend: not running on the laptop (start main.py there before run.py).")

    if args.pull:
        sys.exit(0 if pull() else 1)
    say("To update the code: python3 ~/MakeCU-Fridge/pi_node/link.py --pull")


if __name__ == "__main__":
    main()
