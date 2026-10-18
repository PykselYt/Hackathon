"""Emulates the ESP32 firmware on a virtual serial port (PLAN.md §13), for testing without the board.

    python scripts/fake_esp.py                       # prints the port, e.g. /dev/ttys012
    python -m server.main --serial-port /dev/ttys012

States: ASTEPTARE -> AI (3 valid messages) -> TRANZITIE (no valid message 3 s, or HB stuck)
-> AVARIE -> REVENIRE (3 valid heartbeats) -> AI. Every valid message gets 'ACK:<HB>,L:<lit phase>,S:<AI|AVARIE>'.
Press Ctrl+C to stop; kill it to simulate pulling the data cable.
"""
import os
import re
import sys
import time

if sys.platform == "win32":
    raise SystemExit("fake_esp.py are nevoie de un port serial virtual Unix (pty), care nu exista pe Windows.\n"
                     "Pe Windows: conecteaza placa ESP32 sau porneste cu run_mock.bat / run_demo.bat --no-serial.")

import select  # noqa: E402  (Unix only)
import tty  # noqa: E402  (Unix only)

LINK_TIMEOUT_S = 3.0
TRANSITION_S = 3.0 + 2.0     # yellow 3 s, then all red 2 s
RECOVERY_S = 2.0
MSG = re.compile(r"^P:(\d+),Y:(\d+),Q:(\d+),W:(\d+),M:(AI|FIX),HB:(\d+)$")


def main():
    master, slave = os.openpty()
    tty.setraw(slave)
    print(f"fake ESP32 on {os.ttyname(slave)}", flush=True)
    state, since = "ASTEPTARE", time.monotonic()
    valid_streak, last_valid, last_hb, lit = 0, 0.0, None, 0
    buf = b""

    def go(new):
        nonlocal state, since
        if new != state:
            print(f"{time.strftime('%H:%M:%S')} {state} -> {new}", flush=True)
            state, since = new, time.monotonic()

    while True:
        ready, _, _ = select.select([master], [], [], 0.05)
        now = time.monotonic()
        if ready:
            buf += os.read(master, 1024)
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("ascii", "replace").strip()
                m = MSG.match(line) if len(line) <= 64 else None
                if not m:
                    continue  # malformed lines do not reset the link timer
                p, hb = int(m.group(1)), int(m.group(6))
                if last_hb is not None and hb <= last_hb:
                    continue  # stuck counter = frozen server
                last_hb, last_valid = hb, now
                valid_streak += 1
                if state == "AI":
                    lit = p
                s = "AI" if state == "AI" else "AVARIE"
                os.write(master, f"ACK:{hb},L:{lit},S:{s}\n".encode())
        link_ok = now - last_valid < LINK_TIMEOUT_S
        if not link_ok:
            valid_streak = 0
        if state == "ASTEPTARE" and valid_streak >= 3:
            go("AI")
        elif state == "AI" and not link_ok:
            go("TRANZITIE")
        elif state == "TRANZITIE" and now - since >= TRANSITION_S:
            go("AVARIE")
        elif state == "AVARIE" and valid_streak >= 3:
            go("REVENIRE")
        elif state == "REVENIRE" and now - since >= RECOVERY_S:
            go("AI")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
