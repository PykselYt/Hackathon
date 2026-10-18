"""Serial link to the ESP32 traffic light (PLAN.md §5.4, §5.5, §10).

Sends 'P:..,Y:..,Q:..,W:..,M:..,HB:..' on every phase change and every send_interval_ms, reads 'ACK:..' lines,
reconnects on its own. The board is online while an ACK arrived in the last ack_timeout_ms.
"""
import threading
import time
from pathlib import Path

import serial
import serial.tools.list_ports

from server.schemas import format_serial, parse_ack

RECONNECT_S = 2.0
USB_UART_HINTS = ("CP210", "CH340", "CH910", "USB-SERIAL", "USB SERIAL", "SLAB", "WCH")


def find_port(configured: str) -> str | None:
    """The configured port if it exists, else the first CP210x / CH340 adapter."""
    ports = list(serial.tools.list_ports.comports())
    if any(p.device == configured for p in ports) or Path(configured).exists():
        return configured
    for p in ports:
        text = f"{p.description} {p.manufacturer or ''} {p.hwid}".upper()
        if any(h in text for h in USB_UART_HINTS):
            return p.device
    return None


class SerialBridge(threading.Thread):
    def __init__(self, cfg: dict, on_event, latest_state, log_path: str = "results/serial.log"):
        super().__init__(daemon=True, name="SerialBridge")
        sc = cfg["serial"]
        self.port_name = sc["port"]
        self.baud = sc["baud"]
        self.send_interval = sc["send_interval_ms"] / 1000
        self.ack_timeout = sc["ack_timeout_ms"] / 1000
        self.yellow_ms = int(cfg["tls"]["yellow_s"] * 1000 / cfg["sim"]["speed"])
        self.on_event = on_event
        self.latest_state = latest_state
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.enabled = True
        self.stopping = False
        self.ser: serial.Serial | None = None
        self.hb = 0
        self.last_ack_at: float | None = None
        self.last_ack_mode = "AI"
        self.lit_phase: int | None = None
        self.online = False
        self._lock = threading.Lock()
        self._buf = b""

    # --- any thread ---
    def set_heartbeat(self, enabled: bool) -> None:
        self.enabled = enabled  # paused: the port stays open but nothing is sent, the board falls back on its own

    def stop(self) -> None:
        self.stopping = True

    def status(self) -> dict:
        with self._lock:
            if self.last_ack_at is None:  # never heard from the board
                return {"online": False, "last_ack_ms": None, "mode": "NECONECTAT"}
            age = time.monotonic() - self.last_ack_at
            online = age <= self.ack_timeout
            # a board that answered once and went silent runs its own fail-safe program
            return {"online": online, "last_ack_ms": int(age * 1000), "mode": self.last_ack_mode if online else "AVARIE"}

    # --- bridge thread ---
    def _log(self, text: str) -> None:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {text}\n")

    def _open(self) -> None:
        port = find_port(self.port_name)
        if port is None:
            return
        s = serial.Serial()
        s.port, s.baudrate, s.timeout, s.write_timeout = port, self.baud, 0, 0.5
        # without this the ESP32 reboots every time the port is opened
        s.dtr = False
        s.rts = False
        s.open()
        self.ser = s
        self._buf = b""
        self._log(f"open {port}")

    def _close(self) -> None:
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        with self._lock:
            self.ser = None

    def _read(self) -> None:
        waiting = self.ser.in_waiting
        if not waiting:
            return
        data = self.ser.read(waiting)
        self._buf += data
        while b"\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n", 1)
            line = raw.decode("ascii", "replace").strip()
            ack = parse_ack(line)
            if ack is None:
                if line:
                    self._log(f"ignored: {line[:80]!r}")
                continue
            with self._lock:
                self.last_ack_at = time.monotonic()
                self.last_ack_mode = ack["s"]
                self.lit_phase = ack["l"]

    def _send(self, state: dict) -> None:
        self.hb += 1
        mode = "FIX" if state.get("controller") == "fixed" else "AI"
        line = format_serial(state["phase"], self.yellow_ms, int(state["queue"]), int(round(state["wait"])), mode, self.hb)
        self.ser.write((line + "\n").encode("ascii"))

    def _track_online(self) -> None:
        online = self.status()["online"]
        if online != self.online:
            self.online = online
            if online:
                self.on_event("esp_online", "ESP32 conectat: semaforul fizic urmează AI-ul", "info")
            else:
                self.on_event("esp_offline", "ESP32 offline: semaforul de pe teren trece pe avarie", "error")

    def run(self) -> None:
        last_sent, last_phase = 0.0, None
        while not self.stopping:
            if self.ser is None:
                try:
                    self._open()
                except (serial.SerialException, OSError) as e:
                    self._log(f"open failed: {e}")
                    self._close()
                if self.ser is None:
                    self._track_online()
                    time.sleep(RECONNECT_S)
                    continue
            try:
                self._read()
                state = self.latest_state()
                now = time.monotonic()
                if self.enabled and state is not None:
                    if state["phase"] != last_phase or now - last_sent >= self.send_interval:
                        self._send(state)
                        last_sent, last_phase = now, state["phase"]
            except (serial.SerialException, OSError) as e:
                self._log(f"serial error: {e}")
                self._close()
            self._track_online()
            time.sleep(0.02)
        self._close()
