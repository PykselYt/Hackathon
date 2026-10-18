"""Static network geometry for the 3D map (PLAN.md §5.8), built once from the SUMO network."""
import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path

if "SUMO_HOME" not in os.environ:
    import sumo

    os.environ["SUMO_HOME"] = sumo.SUMO_HOME
import sumolib  # noqa: E402

from server.metrics import approaches_of  # noqa: E402


def _xy(shape) -> list[list[float]]:
    return [[round(x, 2), round(y, 2)] for x, y in shape]


def _lane_kind(edge, lane) -> str | None:
    fn = edge.getFunction()
    if fn in ("crossing", "walkingarea"):
        return fn
    if fn == "internal":
        return None  # covered by the junction polygon
    if lane.allows("pedestrian") and not lane.allows("passenger"):
        return "sidewalk"
    return "road"


def _end_heading(shape) -> float:
    (x0, y0), (x1, y1) = shape[-2], shape[-1]
    return math.degrees(math.atan2(y1 - y0, x1 - x0))


BUILDING_MARGIN_M = 120
DEFAULT_LEVELS = 4
LEVEL_M = 3.2


def _buildings(cfg: dict, bounds: tuple[float, float, float, float]) -> list[dict]:
    """OSM building footprints around the network (same local projection as sumo/src/*.nod.xml)."""
    osm = Path(cfg["sumo"].get("osm", "sumo/map.osm"))
    if not osm.exists():
        return []
    lat0, lon0 = cfg["location"]["lat"], cfg["location"]["lon"]
    kx = math.cos(math.radians(lat0)) * 111320
    xmin, ymin, xmax, ymax = (bounds[0] - BUILDING_MARGIN_M, bounds[1] - BUILDING_MARGIN_M,
                              bounds[2] + BUILDING_MARGIN_M, bounds[3] + BUILDING_MARGIN_M)
    nodes, out = {}, []
    for _, el in ET.iterparse(osm, events=("end",)):
        if el.tag == "node":
            nodes[el.get("id")] = ((float(el.get("lon")) - lon0) * kx, (float(el.get("lat")) - lat0) * 110540)
        elif el.tag == "way":
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            if "building" in tags:
                pts = [nodes[n.get("ref")] for n in el.findall("nd") if n.get("ref") in nodes]
                if len(pts) >= 4 and all(xmin <= x <= xmax and ymin <= y <= ymax for x, y in pts):
                    try:
                        h = float(tags.get("height", "").split()[0])
                    except (ValueError, IndexError):
                        try:
                            h = float(tags.get("building:levels", DEFAULT_LEVELS)) * LEVEL_M
                        except ValueError:
                            h = DEFAULT_LEVELS * LEVEL_M
                    out.append({"shape": _xy(pts[:-1] if pts[0] == pts[-1] else pts), "height": round(h, 1)})
            el.clear()
    return out


def build_network(cfg: dict) -> dict:
    net = sumolib.net.readNet(cfg["sumo"]["net"], withInternal=True, withPrograms=True, withPedestrianConnections=True)
    lanes = []
    for edge in net.getEdges(withInternal=True):
        for lane in edge.getLanes():
            kind = _lane_kind(edge, lane)
            if kind:
                lanes.append({"id": lane.getID(), "kind": kind, "shape": _xy(lane.getShape()), "width": lane.getWidth()})

    junctions = [
        {"id": n.getID(), "shape": _xy(n.getShape()), "tls": n.getType() == "traffic_light"}
        for n in net.getNodes() if len(n.getShape()) >= 3
    ]

    labels = cfg["tls"].get("phase_labels", {})
    lights = []
    for tl_id in cfg["tls"]["ids"]:
        tls = net.getTLS(tl_id)
        program = next(iter(tls.getPrograms().values()))
        greens = [p.state for p in program.getPhases() if "y" not in p.state and set(p.state) & set("Gg")]
        signals: dict[str, dict] = {}
        crossings = []
        approaches: dict[str, dict] = {}
        dirs = approaches_of(net, tl_id)
        for in_lane, out_lane, index in tls.getConnections():
            edge = in_lane.getEdge()
            if edge.getFunction() == "walkingarea" or out_lane.getEdge().getFunction() == "crossing":
                c = out_lane
                crossings.append({"id": c.getID(), "shape": _xy(c.getShape()), "width": c.getWidth(), "link": index})
                continue
            shape = in_lane.getShape()
            s = signals.setdefault(in_lane.getID(), {
                "lane": in_lane.getID(), "pos": [round(shape[-1][0], 2), round(shape[-1][1], 2)],
                "angle": round(_end_heading(shape), 1), "links": [],
            })
            s["links"].append(index)
            d = dirs.get(edge.getID())
            if d is None:
                continue
            a = approaches.setdefault(d, {"dir": d, "name": edge.getName() or edge.getID(), "edge": edge.getID(),
                                          "links": set()})
            a["links"].add(index)
        for a in approaches.values():
            links = a.pop("links")
            a["open"] = [any(st[i] in "Gg" for i in links) for st in greens]
        # the network names each signalised node after its light (sumo/src/*.nod.xml)
        x, y = net.getNode(tl_id).getCoord() if net.hasNode(tl_id) else next(iter(tls.getEdges())).getToNode().getCoord()
        lights.append({
            "id": tl_id,
            "pos": [round(x, 2), round(y, 2)],
            "labels": labels.get(tl_id, [str(i) for i in range(len(greens))]),
            "signals": list(signals.values()),
            "crossings": crossings,
            "approaches": sorted(approaches.values(), key=lambda a: "NESV".index(a["dir"])),
        })

    xmin, ymin, xmax, ymax = net.getBoundary()
    return {"bounds": [round(xmin, 1), round(ymin, 1), round(xmax, 1), round(ymax, 1)],
            "lanes": lanes, "junctions": junctions, "lights": lights,
            "buildings": _buildings(cfg, (xmin, ymin, xmax, ymax))}
