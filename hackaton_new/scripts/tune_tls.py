"""Rewrites the static traffic-light programs of a generated network into clean 2-phase programs.

    python scripts/tune_tls.py sumo/net.net.xml

netconvert adds short pedestrian-clearance and left-turn phases; sumo-rl would treat each of them as a green
phase the agent can pick. We keep the two main green phases of every light (major road / minor road or
pedestrians), insert a yellow between them, and give them the durations from config.yaml (tls.fixed_program).
Pedestrian crossings keep the state netconvert computed for them in each main phase.
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def yellow_between(cur: str, nxt: str, crossing: set[int]) -> str:
    out = []
    for i, (a, b) in enumerate(zip(cur, nxt)):
        if a in "Gg" and b in "rs":
            out.append("r" if i in crossing else "y")
        else:
            out.append(a if a in "rs" or b in "Gg" else "r")
    return "".join(out)


def with_crossings(state: str, crossing_edges: dict[int, set[str]], from_edge: dict[int, str],
                   to_edge: dict[int, str]) -> str:
    """Crossing green when no vehicle leaves the crossed road on green; vehicles turning into it then yield ('g')."""
    st = list(state)
    for i, crossed in crossing_edges.items():
        blocked = any(st[j] in "Gg" and from_edge.get(j) in crossed for j in from_edge)
        st[i] = "r" if blocked else "G"
        if not blocked:
            for j, to in to_edge.items():
                if to in crossed and st[j] == "G":
                    st[j] = "g"
    return "".join(st)


def main(path: str) -> None:
    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    fp = cfg["tls"]["fixed_program"]
    tree = ET.parse(path)
    root = tree.getroot()
    prio = {e.get("id"): int(e.get("priority", "0")) for e in root.iter("edge") if not e.get("function")}
    crossed = {e.get("id"): set(e.get("crossingEdges", "").split()) for e in root.iter("edge") if e.get("function") == "crossing"}
    links: dict[str, dict[int, str]] = {}
    targets: dict[str, dict[int, str]] = {}
    for c in root.iter("connection"):
        if c.get("tl") is not None and c.get("linkIndex") is not None:
            links.setdefault(c.get("tl"), {})[int(c.get("linkIndex"))] = c.get("from")
            targets.setdefault(c.get("tl"), {})[int(c.get("linkIndex"))] = c.get("to")
    for logic in root.iter("tlLogic"):
        tl = logic.get("id")
        phases = logic.findall("phase")
        main_phases = [p for p in phases if "y" not in p.get("state") and set(p.get("state")) & set("Gg")
                       and float(p.get("duration")) >= 15]
        main_phases = sorted(main_phases, key=lambda p: -float(p.get("duration")))[:2]
        main_phases.sort(key=lambda p: phases.index(p))
        crossing = {i for i, frm in links.get(tl, {}).items() if frm.startswith(":")}

        def score(p):  # importance of the vehicle movements a phase serves
            return sum(prio.get(links[tl][i], 0) for i, ch in enumerate(p.get("state")) if ch == "G" and i not in crossing)

        major = max(main_phases, key=score)
        vehicles = {i: f for i, f in links.get(tl, {}).items() if i not in crossing}
        vehicles_to = {i: targets[tl][i] for i in vehicles}
        crossing_edges = {i: crossed.get(targets[tl][i], set()) for i in crossing}
        states = [with_crossings(p.get("state"), crossing_edges, vehicles, vehicles_to) for p in main_phases]
        durs = [fp["major_s"] if p is major else fp["minor_s"] for p in main_phases]
        for p in phases:
            logic.remove(p)
        n = len(states)
        for k in range(n):
            ET.SubElement(logic, "phase", duration=str(durs[k]), state=states[k])
            if n > 1:
                ET.SubElement(logic, "phase", duration=str(cfg["tls"]["yellow_s"]),
                              state=yellow_between(states[k], states[(k + 1) % n], crossing))
        logic.set("offset", "0")
        print(f"{tl}: " + " | ".join(f"{d}s {s}" for d, s in zip(durs, states)))
    ET.indent(tree, space="    ")
    tree.write(path, encoding="UTF-8", xml_declaration=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "sumo/net.net.xml"))
