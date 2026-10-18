"""Data contracts between modules (PLAN.md §5). Mirror of web/src/types.ts — change both together."""
from typing import Literal

from pydantic import BaseModel, Field

PhaseState = Literal["green", "yellow", "all_red"]
EspMode = Literal["AI", "AVARIE", "NECONECTAT"]
VisionSource = Literal["file", "screen", "snapshot", "stream"]
EventKind = Literal[
    "rush_hour", "rush_end", "spillback_hold", "esp_online", "esp_offline",
    "heartbeat_paused", "heartbeat_resumed", "controller_changed", "reset",
    "vision_online", "vision_offline",
]
EventLevel = Literal["info", "warn", "error"]
ControllerName = Literal["ppo", "max_pressure", "fixed"]


# §5.1 WebSocket tick
class SimMetrics(BaseModel):
    avg_wait_s: float
    queue_veh: int
    throughput_vph: float
    trip_wait_s: float


class IntersectionState(BaseModel):
    id: str
    green_phase: int
    phase_label: str
    state: PhaseState
    time_in_phase_s: float
    queues: dict[str, int]          # approach -> halted vehicles ("N", "S", "E", "V")
    hold: bool = False              # spillback_guard is holding the current phase


class EspStatus(BaseModel):
    online: bool
    last_ack_ms: int | None = None  # ms since the last ACK
    mode: EspMode


class VisionStatus(BaseModel):
    online: bool
    source: VisionSource | None = None
    queues: dict[str, int] = Field(default_factory=dict)
    avg_stop_s: float | None = None


class Tick(BaseModel):
    type: Literal["tick"] = "tick"
    sim_time: float
    controller: str
    rush_active: bool
    fix: SimMetrics
    ai: SimMetrics
    improvement_pct: float | None   # null for the first 120 s or < 30 arrived vehicles per sim
    intersections: list[IntersectionState]
    esp: EspStatus
    vision: VisionStatus


# §5.7 WebSocket frame: positions for the 3D map, every simulated second
class SimFrame(BaseModel):
    veh: list[list[float]]          # [id, x, y, angle_deg, kind (0 car, 1 bus), speed_mps]
    ped: list[list[float]]          # [id, x, y, angle_deg]
    tls: dict[str, str]             # light id -> SUMO state string, one char per link index


class Frame(BaseModel):
    type: Literal["frame"] = "frame"
    sim_time: float
    fix: SimFrame
    ai: SimFrame


class History(BaseModel):
    type: Literal["history"] = "history"
    ticks: list[Tick]


# §5.2 WebSocket event
class Event(BaseModel):
    type: Literal["event"] = "event"
    sim_time: float
    kind: EventKind
    level: EventLevel = "info"
    msg: str


# §5.3 REST bodies
class RushRequest(BaseModel):
    vehicles: int | None = None     # default: config rush_hour.vehicles


class ControllerRequest(BaseModel):
    name: ControllerName


class HeartbeatRequest(BaseModel):
    enabled: bool


class SpawnRequest(BaseModel):
    approach: str                   # route id: blv_dir1 | blv_dir2 | lat_in


class OkResponse(BaseModel):
    ok: bool = True


# §5.6 Vision -> server
class VisionReport(BaseModel):
    ts: float
    source: VisionSource
    queues: dict[str, int]
    arrivals_per_min: dict[str, float] = Field(default_factory=dict)
    avg_stop_s: float | None = None


# §5.4 / §5.5 serial lines
def format_serial(p: int, y_ms: int, q: int, w: int, mode: str, hb: int) -> str:
    """Laptop -> ESP32: 'P:1,Y:1500,Q:12,W:34,M:AI,HB:1532' (max 64 chars, '\\n' added by the bridge)."""
    line = f"P:{p},Y:{y_ms},Q:{q},W:{w},M:{mode},HB:{hb}"
    assert len(line) <= 64, line
    return line


def parse_ack(line: str) -> dict | None:
    """ESP32 -> laptop: 'ACK:1532,L:1,S:AI'. Returns {'ack','l','s'} or None if malformed."""
    try:
        parts = dict(p.split(":", 1) for p in line.strip().split(","))
        out = {"ack": int(parts["ACK"]), "l": int(parts["L"]), "s": parts["S"]}
    except (ValueError, KeyError):
        return None
    return out if out["s"] in ("AI", "AVARIE") else None
