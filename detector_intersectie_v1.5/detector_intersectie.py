#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Detector de vehicule in intersectie - LIVE, direct de pe ecran.   (VERSIUNEA 1.5 - Piata Unirii Iasi)

Benzile camerei din Piata Unirii sunt desenate exact pe marcaje (benzi_fixe.json).

Fata de versiunea 1:
 - sensul: vehiculele care coboara pe imagine VIN SPRE INTERSECTIE, cele care urca PLEACA
   (se poate inversa cu --inverseaza-sensul)
 - numara cate vehicule intra / ies si cate stau oprite asteptand sa intre
 - invata singur BENZILE (din traiectorii) si le numeroteaza de la bordura spre mijloc,
   pe fiecare sens: B1 = banda de langa bordura
 - numerele vehiculelor (#) merg pana la 1000, apoi o iau de la 1
 - salveaza numaratorile pe minut in folderul "numaratori" (CSV, se deschide in Excel)

 - captureaza ecranul (sau o zona din el) unde ruleaza camera
 - detecteaza masini, autobuze si tramvaie si le urmareste de la un cadru la altul
 - deseneaza CONTURUL fiecarui vehicul (segmentare), nu un dreptunghi
 - pentru fiecare vehicul: in miscare / oprit (de cat timp) + directia de deplasare
 - invata singur unde e drumul (pe unde circula vehiculele); masinile oprite in afara
   drumului sau nemiscate foarte mult timp sunt considerate parcate si ignorate

Utilizare:
  python detector_intersectie.py                  # live, contururi peste ecran
  python detector_intersectie.py --configurare    # alegi zona de ecran (+ zone optionale)
  python detector_intersectie.py --mod fereastra  # imaginea adnotata intr-o fereastra separata
  python detector_intersectie.py --video clip.mp4 --salveaza rezultat.mp4
"""
import argparse
import json
import math
import os
import sys
import threading
import time
from collections import Counter, deque

import numpy as np
import cv2

AICI = os.path.dirname(os.path.abspath(__file__))
CONFIG_IMPLICIT = os.path.join(AICI, "config_intersectie.json")
DIR_HARTI = os.path.join(AICI, "harti")   # cate o harta a drumului pentru fiecare camera
MODEL_IMPLICIT = "yoloe-26s-seg.pt"
MODEL_REZERVA = "yolo11s-seg.pt"

# ---------------------------------------------------------------------------
# Setari (pot fi ajustate)
# ---------------------------------------------------------------------------
SETARI = dict(
    conf_min=0.15,            # detectiile mai slabe de atat sunt ignorate
    conf_nou=0.35,            # incredere minima ca sa porneasca o pista noua
    fereastra_viteza=2.0,     # secunde de istoric folosite pentru viteza/directie
    # miscare: pixeli/secunda; pragul creste putin cu marimea vehiculului
    miscare_px=2.5, miscare_rel=0.05,
    oprire_px=1.2, oprire_rel=0.025,
    parcat_dupa=120,          # s: nemiscat atat timp -> parcat, chiar si pe drum (nu tramvai/autobuz)
    parcat_afara_nemiscat=4,  # s: in afara drumului, nu s-a miscat deloc -> parcat
    parcat_afara_oprit=15,    # s: in afara drumului, a mers si apoi a stat -> parcat
    parcat_zona_parcare=2,    # s: oprit intr-o zona "parcare" desenata -> parcat
    parcat_harta_neinvatata=45,  # s: cat timp harta drumului inca nu e invatata
    pastrare_miscare=2.0,     # s: cat tinem minte o pista in miscare care a disparut
    pastrare_oprit=8.0,       # s: ... una oprita (ex. acoperita de un tramvai)
    pastrare_parcat=30.0,     # s: ... una parcata
    sens_jos_intra=True,      # True: cine coboara pe imagine vine spre intersectie
    id_maxim=1000,            # dupa #1000 numerotarea o ia de la #1
)

# cuvintele cautate de modelul YOLOE (si categoria in care intra)
PROMPTURI = ["car", "van", "truck", "bus", "tram", "motorcycle"]
NUME_LA_CAT = {"car": "masina", "van": "masina", "truck": "masina", "motorcycle": "masina",
               "bus": "autobuz", "tram": "tramvai", "train": "tramvai"}
NUME_CAT = {"masina": "MASINA", "autobuz": "AUTOBUZ", "tramvai": "TRAMVAI", "transport": "TRANSPORT COMUN"}
TRANSPORT_COMUN = ("autobuz", "tramvai", "transport")   # autobuzele si tramvaiele = o singura categorie

CULORI = {
    ("masina", "miscare"): "#22e03a",
    ("masina", "oprit"): "#ff2d2d",
    ("autobuz", "miscare"): "#1e90ff",
    ("autobuz", "oprit"): "#1e90ff",
    ("tramvai", "miscare"): "#d63cff",
    ("tramvai", "oprit"): "#d63cff",
    ("transport", "miscare"): "#1e90ff",
    ("transport", "oprit"): "#1e90ff",
    "parcat": "#9a9a9a",
    "nou": "#e0e0e0",
    "oprit_tag": "#ff2d2d",
}
CULORI_ZONE = {"drum": "#ffd400", "tramvai": "#d63cff", "parcare": "#9a9a9a"}
CULOARE_HARTA = "#00e5ff"

DIRECTII = ["dreapta", "sus-dreapta", "sus", "sus-stanga", "stanga", "jos-stanga", "jos", "jos-dreapta"]
SAGETI = ["→", "↗", "↑", "↖", "←", "↙", "↓", "↘"]


def hex_bgr(h):
    h = h.lstrip("#")
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


def simplifica_contur(p):
    """Contur de la segmentare -> poligon convex, cu putine puncte."""
    if p is None or len(p) < 3:
        return None
    p = np.asarray(p, np.float32).reshape(-1, 1, 2)
    h = cv2.convexHull(p)
    a = cv2.approxPolyDP(h, max(1.0, 0.012 * cv2.arcLength(h, True)), True).reshape(-1, 2)
    return a if len(a) >= 3 else None


# ---------------------------------------------------------------------------
# Zone optionale desenate de utilizator (coordonate relative 0..1)
# ---------------------------------------------------------------------------
class Zone:
    def __init__(self, zone_rel=None):
        self.rel = {k: [list(map(list, p)) for p in v] for k, v in (zone_rel or {}).items()}
        self.marime = None
        self.px = {}

    def pregateste(self, w, h):
        if self.marime == (w, h):
            return
        self.marime = (w, h)
        self.px = {
            k: [np.array([[x * w, y * h] for x, y in p], np.float32) for p in v if len(p) >= 3]
            for k, v in self.rel.items()
        }

    def are(self, tip):
        return bool(self.px.get(tip))

    def contine(self, tip, pt):
        for p in self.px.get(tip, []):
            if cv2.pointPolygonTest(p, (float(pt[0]), float(pt[1])), False) >= 0:
                return True
        return False


# ---------------------------------------------------------------------------
# Harta drumului, invatata din traseele vehiculelor in miscare
# ---------------------------------------------------------------------------
class HartaTrafic:
    GW, GH = 192, 108

    def __init__(self, cale=None, amprenta=None):
        self.cale = cale
        self.M = np.zeros((self.GH, self.GW), np.float32)
        self.total = 0.0
        self.amprenta = amprenta    # "amprenta" imaginii camerei (vezi amprenta_scena)
        self.benzi = Benzi()
        self._prag_calc = 0.0
        self._prag = float("inf")
        self._Mb = self.M
        self._contur = None
        self._contur_t = 0.0
        self._ultima_salvare = time.time()
        if cale and os.path.exists(cale):
            try:
                d = np.load(cale, allow_pickle=False)
                self.M = d["M"].astype(np.float32)
                self.total = float(d["total"])
                if "amprenta" in d.files:
                    self.amprenta = d["amprenta"].astype(np.float32)
                if "benzi" in d.files:
                    self.benzi = Benzi(json.loads(str(d["benzi"])))
            except Exception as ex:
                print("Nu pot citi harta drumului:", ex)

    def _celule(self, box, W, H, fx=0.2, fy=0.3):
        x1, y1, x2, y2 = box
        w, h = x2 - x1, y2 - y1
        gx1 = int((x1 + fx * w) / W * self.GW)
        gx2 = int(math.ceil((x2 - fx * w) / W * self.GW))
        gy1 = int((y2 - fy * h) / H * self.GH)
        gy2 = int(math.ceil(y2 / H * self.GH))
        gx1, gy1 = max(0, gx1), max(0, gy1)
        gx2, gy2 = min(self.GW, max(gx2, gx1 + 1)), min(self.GH, max(gy2, gy1 + 1))
        return gx1, gy1, gx2, gy2

    def adauga(self, box, dt, W, H):
        gx1, gy1, gx2, gy2 = self._celule(box, W, H)
        self.M[gy1:gy2, gx1:gx2] += dt
        self.total += dt

    def _actualizeaza_prag(self):
        if time.time() - self._prag_calc < 2.0:
            return
        self._prag_calc = time.time()
        v = self.M[self.M > 0]
        if len(v) < 30:
            self._prag = float("inf")
            return
        self._prag = max(1.5, 0.08 * float(np.percentile(v, 90)))
        self._Mb = cv2.GaussianBlur(self.M, (3, 3), 0)

    def invatata(self):
        return self.total >= 180

    def sigura(self):
        """Destul de invatata ca sa decupam imaginea doar la drum."""
        return self.total >= 600

    def e_drum(self, box, W, H):
        self._actualizeaza_prag()
        x1, y1, x2, y2 = box
        gx = min(self.GW - 1, max(0, int((x1 + x2) / 2 / W * self.GW)))
        gy = min(self.GH - 1, max(0, int((y2 - 0.12 * (y2 - y1)) / H * self.GH)))
        return self._Mb[gy, gx] >= self._prag

    def contururi(self, W, H):
        """Conturul zonelor de drum invatate, in pixeli (pentru afisare)."""
        if self._contur is not None and time.time() - self._contur_t < 3:
            return self._contur
        self._actualizeaza_prag()
        masca = (self._Mb >= self._prag).astype(np.uint8) * 255
        masca = cv2.morphologyEx(masca, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        cts, _ = cv2.findContours(masca, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        sx, sy = W / self.GW, H / self.GH
        self._contur = [(c.reshape(-1, 2) * [sx, sy]).astype(np.int32) for c in cts if cv2.contourArea(c) >= 4]
        self._contur_t = time.time()
        return self._contur

    def roi(self, W, H, zone=None):
        """Dreptunghiul care cuprinde drumul invatat (+ margine), sau None."""
        if not self.sigura():
            return None
        if getattr(self, "_roi_t", 0) and time.time() - self._roi_t < 30:
            return self._roi
        self._actualizeaza_prag()
        ys, xs = np.nonzero(self._Mb >= self._prag)
        if len(xs) < 10:
            return None
        x1, x2 = xs.min() / self.GW * W, (xs.max() + 1) / self.GW * W
        y1, y2 = ys.min() / self.GH * H, (ys.max() + 1) / self.GH * H
        if zone is not None:
            zone.pregateste(W, H)
            for polis in zone.px.values():
                for p in polis:
                    x1, y1 = min(x1, p[:, 0].min()), min(y1, p[:, 1].min())
                    x2, y2 = max(x2, p[:, 0].max()), max(y2, p[:, 1].max())
        # margine: lateral 6%, sus 14% (vehiculele se intind deasupra punctului de pe sol), jos 4%
        r = (int(max(0, x1 - 0.06 * W)), int(max(0, y1 - 0.14 * H)),
             int(min(W, x2 + 0.06 * W)), int(min(H, y2 + 0.04 * H)))
        if (r[2] - r[0]) * (r[3] - r[1]) > 0.85 * W * H:
            r = None
        vechi = getattr(self, "_roi", None)
        if vechi is None or r is None or max(abs(a - b) for a, b in zip(r, vechi)) > 0.04 * max(W, H):
            self._roi = r      # schimbam doar daca difera clar (forma stabila = mai rapid)
        self._roi_t = time.time()
        return self._roi

    def salveaza(self, fortat=False):
        if not self.cale or (not fortat and time.time() - self._ultima_salvare < 60):
            return
        self._ultima_salvare = time.time()
        try:
            extra = {} if self.amprenta is None else {"amprenta": self.amprenta}
            extra["benzi"] = json.dumps(self.benzi.date())
            np.savez_compressed(self.cale, M=self.M, total=np.float64(self.total), **extra)
        except Exception as ex:
            print("Nu pot salva harta drumului:", ex)


def amprenta_scena(frame):
    """Contururile statice ale imaginii (cladiri, borduri, marcaje) la rezolutie mica.
    Nu depinde mult de lumina; doua camere diferite dau amprente foarte diferite."""
    g = cv2.cvtColor(cv2.resize(frame, (128, 72), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g.astype(np.float32), (3, 3), 0)
    m = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    m = m[8:68, 4:124]                     # fara marginile cu texte / ceas
    m = np.sqrt(m)
    return _normeaza(m)


def _normeaza(a):
    a = a.astype(np.float32) - a.mean()
    return a / (a.std() + 1e-6)


def similaritate(a, b):
    if a is None or b is None or a.shape != b.shape:
        return -1.0
    return float(np.mean(a * b))


class ManagerHarti:
    """Recunoaste camera dupa amprenta imaginii si foloseste harta drumului potrivita.
    Camera noua -> harta noua (invata de la zero). Camera schimbata in timpul rularii -> comuta."""
    PRAG = 0.45            # similaritate minima ca sa fie "aceeasi camera"
    INTERVAL = 0.5         # s intre doua masuratori ale amprentei
    VERIFICARE = 10.0      # s intre doua verificari ca e tot aceeasi camera

    def __init__(self, director=DIR_HARTI, reseteaza=False, reseteaza_benzi=False):
        self.dir = director
        self.reseteaza = reseteaza
        self.reseteaza_benzi = reseteaza_benzi
        self.harta = HartaTrafic()          # temporara, pana recunoastem camera
        self.aleasa = False
        self.acc = None
        self.n = 0
        self._t_obs = -1e9
        self._t_verif = 0.0
        self.nepotriviri = 0
        self.mesaj = ""

    def _biblioteca(self):
        rez = []
        if os.path.isdir(self.dir):
            for f in sorted(os.listdir(self.dir)):
                if f.endswith(".npz"):
                    cale = os.path.join(self.dir, f)
                    try:
                        with np.load(cale, allow_pickle=False) as d:
                            if "amprenta" in d.files:
                                rez.append((cale, d["amprenta"].astype(np.float32)))
                    except Exception:
                        pass
        return rez

    def _alege(self):
        cel_mai_bun, sim_max = None, -1.0
        for cale, fp in self._biblioteca():
            sim = similaritate(self.acc, fp)
            if sim > sim_max:
                cel_mai_bun, sim_max = cale, sim
        if cel_mai_bun and sim_max >= self.PRAG and not self.reseteaza:
            self.harta = HartaTrafic(cel_mai_bun)
            if self.reseteaza_benzi:
                self.harta.benzi.reseteaza()
                self.reseteaza_benzi = False
                print("Benzile camerei sterse - le invat din nou.")
            self.mesaj = (f"Camera recunoscuta ({os.path.basename(cel_mai_bun)}, "
                          f"{self.harta.total / 60:.0f} min de trafic invatat).")
        else:
            if cel_mai_bun and sim_max >= self.PRAG and self.reseteaza:
                try:
                    os.remove(cel_mai_bun)
                except OSError:
                    pass
            os.makedirs(self.dir, exist_ok=True)
            cale = os.path.join(self.dir, time.strftime("camera_%Y%m%d_%H%M%S.npz"))
            self.harta = HartaTrafic(cale, self.acc.copy())
            self.harta.salveaza(fortat=True)
            self.mesaj = "Camera noua: invat drumul de la zero (cateva minute de trafic)."
        self.reseteaza = False
        print(self.mesaj)
        self.aleasa = True
        self.nepotriviri = 0

    def observa(self, frame, t):
        """Apelat la fiecare cadru. Intoarce True daca s-a schimbat camera (harta)."""
        if t - self._t_obs < self.INTERVAL:
            return False
        self._t_obs = t
        fp = amprenta_scena(frame)
        self.acc = fp if self.acc is None else _normeaza(0.7 * self.acc + 0.3 * fp)
        self.n += 1
        if not self.aleasa:
            if self.n >= 4:           # ~2 s de imagine, ca vehiculele sa nu conteze
                self._alege()
                return True
            return False
        h = self.harta
        if t - self._t_verif < self.VERIFICARE:
            return False
        self._t_verif = t
        sim = similaritate(self.acc, h.amprenta)
        if sim >= self.PRAG:
            self.nepotriviri = 0
            h.amprenta = _normeaza(0.9 * h.amprenta + 0.1 * self.acc)  # urmareste zi/noapte lent
            return False
        self.nepotriviri += 1
        if self.nepotriviri >= 2:     # 2 verificari la rand: alta camera
            h.salveaza(fortat=True)
            print("Imaginea s-a schimbat - caut harta camerei noi...")
            self._alege()
            return True
        return False


def _are_vai(x, mu, sigma):
    """Intre oricare doua benzi vecine densitatea scade clar (sub jumatate din varfuri)."""
    h = max(0.5 * sigma, 1e-3)
    grila = np.linspace(min(mu) - sigma, max(mu) + sigma, 400)
    dens = np.exp(-0.5 * ((grila[:, None] - x[None, :]) / h) ** 2).sum(1)
    f = lambda v: np.interp(v, grila, dens)
    for a, b in zip(mu, mu[1:]):
        intre = dens[(grila >= a) & (grila <= b)]
        if len(intre) == 0 or intre.min() > 0.5 * min(f(a), f(b)):
            return False
    return True


def gmm_1d(x, kmax=4):
    """Grupeaza valori 1D in 1..kmax grupuri de aceeasi latime (benzi). Alege numarul cu BIC."""
    x = np.asarray(x, np.float64)
    n = len(x)
    cel_mai_bun = None
    for k in range(1, kmax + 1):
        mu = np.quantile(x, (np.arange(k) + 0.5) / k)
        s2 = max(np.var(x) / (k * k), 1e-6)
        w = np.full(k, 1.0 / k)
        for _ in range(60):
            ll = -0.5 * (x[:, None] - mu) ** 2 / s2 - 0.5 * np.log(2 * np.pi * s2) + np.log(w + 1e-12)
            m = ll.max(1, keepdims=True)
            r = np.exp(ll - m)
            tot = r.sum(1, keepdims=True)
            r /= tot
            Nk = r.sum(0) + 1e-9
            w = Nk / n
            mu = (r * x[:, None]).sum(0) / Nk
            s2 = max(float((r * (x[:, None] - mu) ** 2).sum() / n), 1e-6)
        loglik = float((m[:, 0] + np.log(tot[:, 0])).sum())
        ordine = np.argsort(mu)
        mu, w = mu[ordine], w[ordine]
        if k > 1 and (w.min() < 0.06 or np.diff(mu).min() < 3.0 * math.sqrt(s2)):
            continue                      # grupuri prea mici sau suprapuse: nu sunt benzi reale
        if k > 1 and not _are_vai(x, mu, math.sqrt(s2)):
            continue                      # intre doua "benzi" nu e gol: e de fapt una singura
        bic = -2 * loglik + (2 * k) * math.log(n)
        if cel_mai_bun is None or bic < cel_mai_bun[0]:
            cel_mai_bun = (bic, mu.tolist(), math.sqrt(s2))
    return cel_mai_bun[1], cel_mai_bun[2]


class Benzi:
    """Invata benzile din traiectorii, pentru fiecare strada vazuta de camera.
    O strada privita in lung are toate benzile convergand spre un punct de fuga (VP); o
    intersectie vazuta de sus are mai multe strazi = mai multe puncte de fuga. Pentru fiecare
    strada, unghiul vehiculelor fata de VP se strange in grupuri = benzi, numerotate de la
    bordura (dreapta sensului de mers) spre mijloc: B1 = langa bordura."""
    MAX_STRAZI = 3

    def __init__(self, date=None):
        self.linii = deque(maxlen=800)    # (x, y, dx, dy): bucati drepte de traiectorie
        self.puncte = deque(maxlen=8000)  # (x, y, sens, dx, dy) vehicule in miscare
        self.strazi = []                  # [{"vp": (x,y), "grupuri": {sens: {...}}, "r": (rmin,rmax)}]
        self._t_calc = -1e9
        self.fixe = None                  # benzi desenate pentru o camera anume (din config)
        self._fixe_px = None
        self._fixe_marime = None
        if date:
            try:
                self.linii.extend(tuple(l) for l in date.get("linii", []))
                self.puncte.extend(tuple(q) for q in date.get("puncte", []) if len(q) == 5)
                for st in date.get("strazi", []):
                    st["vp"] = tuple(st["vp"])
                    st["grupuri"] = {int(k): v for k, v in st["grupuri"].items()}
                    self.strazi.append(st)
            except Exception:
                self.strazi = []

    def date(self):
        return {"linii": [list(map(float, l)) for l in list(self.linii)[-400:]],
                "puncte": [list(map(float, q)) for q in list(self.puncte)[-4000:]],
                "strazi": [{"vp": list(st["vp"]), "r": list(st["r"]),
                            "grupuri": {str(k): v for k, v in st["grupuri"].items()},
                            "candidat": st.get("candidat", {})}
                           for st in self.strazi]}

    def gata(self):
        return bool(self.fixe) or any(st["grupuri"] for st in self.strazi)

    def seteaza_fixe(self, date):
        """Benzi exacte, desenate pe marcaje (ex. Piata Unirii). Inlocuiesc invatarea automata.
        date = lista de benzi sau {"benzi": [...], "parcari": [poligoane]}"""
        if isinstance(date, dict):
            self.fixe = date.get("benzi") or None
            self.parcari = date.get("parcari") or []
        else:
            self.fixe, self.parcari = (date or None), []
        self._fixe_marime = None

    parcari = []

    def in_parcare(self, x, y):
        if not self.parcari:
            return False
        W, H = getattr(self, "_marime", (1, 1))
        if getattr(self, "_parc_marime", None) != (W, H):
            self._parc_marime = (W, H)
            self._parc_px = [np.array([[a * W, b_ * H] for a, b_ in p], np.float32) for p in self.parcari]
        return any(cv2.pointPolygonTest(p, (float(x), float(y)), False) >= 0 for p in self._parc_px)

    def _px(self, W, H):
        if self._fixe_marime != (W, H):
            self._fixe_marime = (W, H)
            self._fixe_px = [np.array([[x * W, y * H] for x, y in b["poligon"]], np.float32)
                             for b in self.fixe]
        return self._fixe_px

    @staticmethod
    def _unghi(vp, x, y):
        return math.degrees(math.atan2(x - vp[0], y - vp[1]))

    @staticmethod
    def _aliniere(vp, x, y, d):
        """|cos| intre directia de mers si directia spre punctul de fuga."""
        v = np.array([x - vp[0], y - vp[1]])
        nv = np.linalg.norm(v)
        return abs(float(np.dot(d, v)) / nv) if nv > 1 else 0.0

    def _strada(self, x, y, d, grade=15):
        if d is None:
            return None
        best, best_c = None, math.cos(math.radians(grade))
        for i, st in enumerate(self.strazi):
            c = self._aliniere(st["vp"], x, y, d)
            if c >= best_c:
                best, best_c = i, c
        return best

    def pe_axa(self, x, y, d):
        """Merge in lungul unei strazi cunoscute (nu vireaza)? Inainte sa stim strazile: da."""
        return not self.strazi or self._strada(x, y, d) is not None

    def adauga_linie(self, pts):
        pts = np.asarray(pts, np.float64)
        c = pts.mean(0)
        _, sv, vt = np.linalg.svd(pts - c, full_matrices=False)
        if len(sv) < 2 or sv[0] < 3 * max(sv[1], 1e-6):
            return                        # traiectorie curba (viraj) -> nu ajuta
        self.linii.append((c[0], c[1], vt[0][0], vt[0][1]))

    def adauga_punct(self, x, y, sens, d):
        self.puncte.append((x, y, sens, float(d[0]), float(d[1])))

    @staticmethod
    def _vp_ransac(L, minim):
        P, D = L[:, :2], L[:, 2:]
        N = np.stack([-D[:, 1], D[:, 0]], 1)
        b = (N * P).sum(1)
        rng = np.random.default_rng(len(L))
        cos_tol = math.cos(math.radians(4.0))
        best_in = None
        for _ in range(500):
            i, j = rng.choice(len(L), 2, replace=False)
            A = N[[i, j]]
            if abs(np.linalg.det(A)) < 1e-3:
                continue
            v = np.linalg.solve(A, b[[i, j]])
            vec = v - P
            inl = np.abs((vec * D).sum(1)) / (np.linalg.norm(vec, axis=1) + 1e-9) >= cos_tol
            if best_in is None or inl.sum() > best_in.sum():
                best_in = inl
        if best_in is None or best_in.sum() < minim:
            return None, None
        v, *_ = np.linalg.lstsq(N[best_in], b[best_in], rcond=None)
        return (float(v[0]), float(v[1])), best_in

    def recalculeaza(self, t, W, H):
        self._marime = (W, H)
        if self.fixe:
            return
        if t - self._t_calc < 15 or len(self.linii) < 30:
            return
        self._t_calc = t
        L = np.array(self.linii)
        vps = []
        while len(L) >= 10 and len(vps) < self.MAX_STRAZI:   # cate o strada pe rand
            vp, inl = self._vp_ransac(L, max(10, 0.15 * len(self.linii)))
            if vp is None:
                break
            if abs(vp[0]) < 20 * W and abs(vp[1]) < 20 * H:
                vps.append(vp)
            L = L[~inl]
        if not vps:
            return
        Pt = np.array(self.puncte) if self.puncte else np.zeros((0, 5))
        strazi = []
        for vp in vps:
            grupuri, raze = {}, []
            for sens in (1, -1):
                u = []
                for x, y, s_, dx, dy in Pt:
                    if s_ != sens or self._aliniere(vp, x, y, (dx, dy)) < math.cos(math.radians(12)):
                        continue
                    u.append(self._unghi(vp, x, y))
                    raze.append(math.hypot(x - vp[0], y - vp[1]))
                if len(u) < 80:          # destule masini pe strada asta, ca benzile sa fie sigure
                    continue
                mu, sig = gmm_1d(u)
                # bordura = dreapta sensului de mers: spre camera (in jos) e in stanga imaginii
                jos = (sens == 1) == SETARI["sens_jos_intra"]
                grupuri[sens] = {"mu": mu if jos else mu[::-1], "sigma": sig}
            if grupuri:
                strazi.append({"vp": vp, "grupuri": grupuri,
                               "r": (float(np.percentile(raze, 3)), float(np.percentile(raze, 97)))})
        if strazi:
            self._combina(strazi, Pt, W, H)

    def _combina(self, noi, Pt, W, H):
        """Benzile odata gasite NU dispar cand traficul scade: numarul de benzi doar creste
        (si doar daca noul numar apare de doua ori la rand). Pozitiile se ajusteaza fin."""
        prag_vp = 0.08 * max(W, H)
        for st_n in noi:
            vechi = None
            for st in self.strazi:
                if math.dist(st["vp"], st_n["vp"]) < prag_vp:
                    vechi = st
                    break
            if vechi is None:
                # o strada "noua" ale carei masini merg de fapt spre punctul de fuga al unei
                # strazi deja stiute (ex. trafic doar pe o banda) = aceeasi strada, nu adaugam
                if not self._acoperita(st_n, Pt) and len(self.strazi) < self.MAX_STRAZI:
                    self.strazi.append(st_n)
                continue
            vechi["vp"] = tuple(0.8 * np.array(vechi["vp"]) + 0.2 * np.array(st_n["vp"]))
            vechi["r"] = (min(vechi["r"][0], st_n["r"][0]), max(vechi["r"][1], st_n["r"][1]))
            cand = vechi.setdefault("candidat", {})
            for sens, g_n in st_n["grupuri"].items():
                g_v = vechi["grupuri"].get(sens)
                k_n = len(g_n["mu"])
                if g_v is None:
                    vechi["grupuri"][sens] = g_n
                    continue
                k_v = len(g_v["mu"])
                if k_n > k_v:
                    if cand.get(str(sens)) == k_n:      # a doua oara la rand: acceptam
                        vechi["grupuri"][sens] = g_n
                        cand.pop(str(sens), None)
                    else:
                        cand[str(sens)] = k_n
                    continue
                cand.pop(str(sens), None)
                if k_n == k_v:
                    vechi["grupuri"][sens] = g_n          # acelasi numar: pozitii actualizate
                # k_n < k_v: trafic putin / o singura banda folosita -> pastram benzile stiute

    def _acoperita(self, st_n, Pt):
        if not self.strazi or len(Pt) == 0:
            return False
        c12, c6 = math.cos(math.radians(12)), math.cos(math.radians(6))
        ale_ei = [q for q in Pt if self._aliniere(st_n["vp"], q[0], q[1], (q[3], q[4])) >= c12]
        if not ale_ei:
            return False
        for st in self.strazi:
            ok = sum(self._aliniere(st["vp"], q[0], q[1], (q[3], q[4])) >= c6 for q in ale_ei)
            if ok >= 0.6 * len(ale_ei):
                return True
        return False

    def reseteaza(self):
        self.linii.clear()
        self.puncte.clear()
        self.strazi = []

    def banda(self, x, y, sens, d):
        """Intoarce (strada, sens, nr_banda) sau None."""
        if self.fixe:
            W, H = getattr(self, "_marime", (1, 1))
            for b, poly in zip(self.fixe, self._px(W, H)):
                if cv2.pointPolygonTest(poly, (float(x), float(y)), False) >= 0:
                    return b["strada"], b["sens"], b["nr"]
            return None
        if not self.gata():
            return None
        idx = self._strada(x, y, d, grade=20) if d is not None else None
        candidati = [idx] if idx is not None else range(len(self.strazi))
        for i in candidati:
            st = self.strazi[i]
            u = self._unghi(st["vp"], x, y)
            s_try = [sens] if sens is not None else list(st["grupuri"])
            for s_ in s_try:
                g = st["grupuri"].get(s_)
                if g is None:
                    continue
                dist = [abs(u - m) for m in g["mu"]]
                k = int(np.argmin(dist))
                if dist[k] <= 2.5 * g["sigma"]:
                    return i, s_, k + 1
        return None

    def nume(self, b):
        """Textul benzii: 'B2' (o strada) sau 'S2 B1' (mai multe strazi)."""
        if not b:
            return None
        if isinstance(b[0], str):
            return f"{b[0]} B{b[2]}"
        return f"B{b[2]}" if len(self.strazi) <= 1 else f"S{b[0] + 1} B{b[2]}"

    def rezumat(self):
        if self.fixe:
            rez = {}
            for b in self.fixe:
                r = rez.setdefault(b["strada"], [b["strada"], 0, 0])
                r[1 if b["sens"] == 1 else 2] += 1
            return [tuple(v) for v in rez.values()]
        return [(i + 1, len(st["grupuri"].get(1, {}).get("mu", [])),
                 len(st["grupuri"].get(-1, {}).get("mu", []))) for i, st in enumerate(self.strazi)]

    def desen(self, W, H):
        """Linii de separare a benzilor + etichete, doar pe portiunea unde circula vehicule."""
        rez = []
        if self.fixe:
            for b, poly in zip(self.fixe, self._px(W, H)):
                col = "#ffd400" if b["sens"] == 1 else "#00e5ff"
                rez.append(("poligon", poly.tolist(), col, None))
                ys = poly[:, 1]
                jos = poly[ys >= ys.min() + 0.75 * (ys.max() - ys.min())]   # eticheta spre camera
                cx, cy = jos.mean(0)
                if b["strada"] != "Bd":
                    cx, cy = poly.mean(0)
                rez.append(("text", [(float(cx), float(cy))], col, f"{b['strada']} B{b['nr']}"))
            return rez
        for i, st in enumerate(self.strazi):
            vx, vy = st["vp"]
            r0, r1 = st["r"]
            for sens, g in st["grupuri"].items():
                mu = sorted(g["mu"])
                jum = (np.median(np.diff(mu)) / 2) if len(mu) > 1 else 2 * g["sigma"]
                margini = [mu[0] - jum] + [(a + b) / 2 for a, b in zip(mu, mu[1:])] + [mu[-1] + jum]
                col = "#ffd400" if sens == 1 else "#00e5ff"
                for u in margini:
                    sx, sy = math.sin(math.radians(u)), math.cos(math.radians(u))
                    rez.append(("linie", [(vx + sx * r0, vy + sy * r0), (vx + sx * r1, vy + sy * r1)], col, None))
                for nr, u in enumerate(g["mu"], 1):
                    sx, sy = math.sin(math.radians(u)), math.cos(math.radians(u))
                    r = r0 + 0.85 * (r1 - r0)
                    txt = f"B{nr}" if len(self.strazi) <= 1 else f"S{i + 1}B{nr}"
                    rez.append(("text", [(vx + sx * r, vy + sy * r)], col, txt))
        return rez


class JurnalMinut:
    """Numaratorile pe minut -> CSV (folderul numaratori). Se deschide direct in Excel."""

    def __init__(self, director, nume="camera"):
        self.dir, self.nume = director, nume
        self.minut = None
        self.cont = Counter()          # (tip, banda, categorie) -> numar
        self.asteapta_max = Counter()  # banda -> maximul de vehicule care asteapta in minut

    def _eticheta_minut(self, t):
        if t > 1e9:
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))
        return f"video {int(t // 3600):02d}:{int(t // 60) % 60:02d}"

    def tic(self, t):
        m = int(t // 60)
        if self.minut is None:
            self.minut = m
        elif m != self.minut:
            self.scrie()
            self.minut = m

    def scrie(self):
        if self.dir is None or self.minut is None or (not self.cont and not self.asteapta_max):
            self.cont, self.asteapta_max = Counter(), Counter()
            return
        import csv
        os.makedirs(self.dir, exist_ok=True)
        cale = os.path.join(self.dir, f"{self.nume}_{time.strftime('%Y%m%d')}.csv")
        nou = not os.path.exists(cale)
        et = self._eticheta_minut(self.minut * 60)
        randuri = Counter()
        for (tip, banda, cat), n in self.cont.items():
            randuri[(tip, banda, cat)] += n
        try:
            with open(cale, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                if nou:
                    w.writerow(["minut", "tip", "banda", "masini", "transport_comun"])
                chei = sorted({(tip, b) for tip, b, _ in randuri})
                for tip, b in chei:
                    w.writerow([et, tip, b, randuri[(tip, b, "masina")], randuri[(tip, b, "transport")]])
                for b, n in sorted(self.asteapta_max.items()):
                    w.writerow([et, "asteapta_max", b, n, ""])
        except Exception as ex:
            print("Nu pot scrie numaratorile:", ex)
        self.cont, self.asteapta_max = Counter(), Counter()


# ---------------------------------------------------------------------------
# Urmarire (tracking)
# ---------------------------------------------------------------------------
def iou_matrice(a, b):
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    ab = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / (aa[:, None] + ab[None, :] - inter + 1e-9)


def ioa_matrice(a, b):
    """Intersectia raportata la aria chenarului din a (cat din a e acoperit de b)."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    return inter / (aa[:, None] + 1e-9)


class Pista:
    _urmatorul = 1
    _nr_urmator = 1      # numarul afisat (#12), dat doar vehiculelor confirmate

    def __init__(self, box, conf, cat, poly, t):
        self.id = Pista._urmatorul
        Pista._urmatorul += 1
        self.nr = None
        self.box = np.array(box, float)
        self.poligon = poly
        self.vel = np.zeros(2)
        self.t_start = self.t_ultim = t
        self.hits = 1
        self.voturi = Counter()
        self.voturi[cat] += conf
        self.istoric = deque()
        self._adauga_istoric(t)
        self.poz_start = self.centru()
        self.stare = "nou"          # nou / miscare / oprit
        self.a_miscat = False       # a parcurs cel putin o lungime de vehicul
        self.parcurs = 0.0
        self.t_oprit = t
        self.parcat = False
        self.poz_parcare = None
        self.directie = None        # vector unitate (dx, dy) in coordonate ecran
        self.sens = None            # +1 = vine spre intersectie, -1 = pleaca (ultimul sens cunoscut)
        self.benzi = Counter()      # voturi pentru banda (sens, nr)
        self.banda = None
        self.numarat = False
        self._t_linie = -1e9
        self._t_punct = -1e9

    def centru(self):
        b = self.box
        return np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2])

    def inaltime(self):
        return max(4.0, self.box[3] - self.box[1])

    def categorie(self):
        return self.voturi.most_common(1)[0][0]

    def _adauga_istoric(self, t):
        self.istoric.append((t, *self.box))
        while self.istoric and t - self.istoric[0][0] > 5.0:
            self.istoric.popleft()

    def box_prezis(self, t):
        if self.stare == "oprit" or self.parcat or self.hits < 2:
            return self.box
        dt = min(t - self.t_ultim, 1.0)
        dx, dy = self.vel * dt
        return self.box + np.array([dx, dy, dx, dy])

    def actualizeaza(self, box, conf, cat, poly, t):
        dt = t - self.t_ultim
        c_vechi = self.centru()
        self.box = 0.3 * self.box_prezis(t) + 0.7 * np.asarray(box, float)
        self.poligon = poly
        if dt > 1e-3:
            inst = (self.centru() - c_vechi) / dt
            self.vel = inst if self.hits == 1 else 0.6 * self.vel + 0.4 * inst
        self.t_ultim = t
        self.hits += 1
        self.voturi[cat] += conf
        self._adauga_istoric(t)

    def pastrare(self):
        if self.parcat:
            return SETARI["pastrare_parcat"]
        if self.stare == "miscare":
            return SETARI["pastrare_miscare"]
        return SETARI["pastrare_oprit"]


class Urmaritor:
    def __init__(self):
        self.piste = []

    @staticmethod
    def _similaritate(A, B, pierdut=None):
        iou = iou_matrice(A, B)
        ca = np.stack([(A[:, 0] + A[:, 2]) / 2, (A[:, 1] + A[:, 3]) / 2], 1)
        cb = np.stack([(B[:, 0] + B[:, 2]) / 2, (B[:, 1] + B[:, 3]) / 2], 1)
        d = np.linalg.norm(ca[:, None] - cb[None], axis=2)
        sz = np.maximum(A[:, 2] - A[:, 0], A[:, 3] - A[:, 1])[:, None]
        # o pista disparuta de curand poate fi regasita mai departe (acelasi vehicul, acelasi ID)
        poarta = 0.8 + (0.7 * np.minimum(pierdut, 2.0)[:, None] if pierdut is not None else 0)
        scor_dist = np.clip(1 - d / (poarta * sz + 1e-9), 0, 1)
        ha = (A[:, 3] - A[:, 1])[:, None]
        hb = (B[:, 3] - B[:, 1])[None, :]
        raport = np.minimum(ha, hb) / (np.maximum(ha, hb) + 1e-9)
        return np.maximum(iou, 0.6 * scor_dist) * (raport > 0.45)

    def _asociaza(self, idx_piste, idx_det, boxes, t, prag, doar_iou=False):
        if not idx_piste or len(idx_det) == 0:
            return [], idx_piste, list(idx_det)
        from scipy.optimize import linear_sum_assignment
        A = np.array([self.piste[i].box_prezis(t) for i in idx_piste])
        B = boxes[idx_det]
        pierdut = np.array([t - self.piste[i].t_ultim for i in idx_piste])
        # piste tinere (viteza inca necunoscuta): fereastra de cautare mai mare
        pierdut = pierdut + np.array([0.6 if self.piste[i].hits < 3 else 0.0 for i in idx_piste])
        S = iou_matrice(A, B) if doar_iou else self._similaritate(A, B, pierdut)
        r, c = linear_sum_assignment(-S)
        perechi, fol_p, fol_d = [], set(), set()
        for i, j in zip(r, c):
            if S[i, j] >= prag:
                perechi.append((idx_piste[i], idx_det[j]))
                fol_p.add(i)
                fol_d.add(j)
        rest_p = [p for k, p in enumerate(idx_piste) if k not in fol_p]
        rest_d = [d for k, d in enumerate(idx_det) if k not in fol_d]
        return perechi, rest_p, rest_d

    def actualizeaza(self, boxes, confs, cats, polys, t):
        idx_mare = [i for i in range(len(boxes)) if confs[i] >= SETARI["conf_nou"]]
        idx_mic = [i for i in range(len(boxes)) if confs[i] < SETARI["conf_nou"]]
        toate = list(range(len(self.piste)))
        p1, rest_p, rest_d = self._asociaza(toate, idx_mare, boxes, t, 0.2)
        p2, rest_p, _ = self._asociaza(rest_p, idx_mic, boxes, t, 0.3, doar_iou=True)
        for ip, idd in p1 + p2:
            self.piste[ip].actualizeaza(boxes[idd], confs[idd], cats[idd], polys[idd], t)
        ocupate = [p.box for p in self.piste if t - p.t_ultim < 1.0]
        for idd in sorted(rest_d, key=lambda i: -confs[i]):
            if ocupate:
                E = np.array(ocupate)
                d = boxes[idd:idd + 1]
                if ioa_matrice(d, E).max() > 0.7 or ioa_matrice(E, d).max() > 0.85:
                    continue  # chenar in plus peste un vehicul deja urmarit -> nu facem pista noua
            self.piste.append(Pista(boxes[idd], confs[idd], cats[idd], polys[idd], t))
            ocupate.append(np.asarray(boxes[idd], float))
        self._contopeste_dubluri(t)
        self.piste = [p for p in self.piste if t - p.t_ultim <= p.pastrare()]
        folosite = None
        for p in self.piste:
            if p.nr is None and p.hits >= 2:
                if folosite is None:
                    folosite = {q.nr for q in self.piste if q.nr is not None}
                for _ in range(SETARI["id_maxim"]):      # urmatorul numar liber, 1..1000
                    nr = Pista._nr_urmator
                    Pista._nr_urmator = nr % SETARI["id_maxim"] + 1
                    if nr not in folosite:
                        break
                p.nr = nr
                folosite.add(nr)

    def _contopeste_dubluri(self, t):
        """Doua piste pe acelasi vehicul (ex. 'masina' + 'duba' pe aceeasi masina, sau bucati
        dintr-un tramvai) -> pastram una singura, cu ID-ul cel mai vechi."""
        act = [p for p in self.piste if p.t_ultim == t]
        if len(act) < 2:
            self._suprapuneri = {}
            return
        B = np.array([p.box for p in act])
        M = ioa_matrice(B, B)              # cat din chenarul i e acoperit de j
        noi, sterse = {}, set()
        for i, pi in enumerate(act):
            for j, pj in enumerate(act):
                if i == j or M[i, j] < 0.8 or pi.id in sterse or pj.id in sterse:
                    continue
                cheie = (pi.id, pj.id)
                noi[cheie] = getattr(self, "_suprapuneri", {}).get(cheie, 0) + 1
                mare = pj.categorie() in TRANSPORT_COMUN and pi.categorie() == "masina"
                if noi[cheie] >= (1 if mare else 3):
                    # pi e (aproape) in intregime in pj de mai multe cadre: e acelasi vehicul
                    pastrat, sters = (pj, pi) if (mare or pj.id < pi.id) else (pi, pj)
                    pastrat.voturi.update(sters.voturi) if not mare else None
                    pastrat.hits = max(pastrat.hits, sters.hits)
                    if sters.nr is not None and (pastrat.nr is None or sters.nr < pastrat.nr) and not mare:
                        pastrat.nr = sters.nr
                    sterse.add(sters.id)
        self._suprapuneri = noi
        if sterse:
            self.piste = [p for p in self.piste if p.id not in sterse]


# ---------------------------------------------------------------------------
# Analiza: miscare / oprit / parcat / directie
# ---------------------------------------------------------------------------
class Analizor:
    def __init__(self, zone, harti=None, benzi_fixe=None):
        self.zone = zone
        self.benzi_fixe = benzi_fixe or {}     # nume camera -> benzi desenate
        self.harti = harti or ManagerHarti(director=None)
        self.urm = Urmaritor()
        self.t = 0.0
        self.marime = (1, 1)
        self.total = Counter()           # ("intra"/"iese", categorie) de la pornire
        self.total_banda = Counter()     # ("intra"/"iese", banda) de la pornire
        self.jurnal = JurnalMinut(None)
        self._harta_jurnal = None

    @property
    def harta(self):
        return self.harti.harta

    def observa_cadru(self, frame, t):
        """Recunoaste camera; daca s-a schimbat, uitam vehiculele urmarite."""
        if self.harti.dir is not None and self.harti.observa(frame, t):
            self.urm = Urmaritor()

    def actualizeaza(self, boxes, confs, cats, polys, t, marime):
        dt = t - self.t if self.t else 0.0
        self.t = t
        self.marime = marime
        self.zone.pregateste(*marime)
        boxes = np.asarray(boxes, float).reshape(-1, 4)
        cats = list(cats)
        if polys is None:
            polys = [None] * len(boxes)
        for i, b in enumerate(boxes):
            if cats[i] == "autobuz" and self.zone.contine("tramvai", ((b[0] + b[2]) / 2, b[3])):
                cats[i] = "tramvai"  # doar daca utilizatorul a desenat zona de tramvai
        cats = ["transport" if c in TRANSPORT_COMUN else c for c in cats]
        self.urm.actualizeaza(boxes, np.asarray(confs, float), cats, polys, t)
        self._jurnal_camera()
        self.jurnal.tic(t)
        self.harta.benzi._marime = marime
        for p in self.urm.piste:
            if p.t_ultim == t:
                self._analizeaza(p, t)
                if p.stare == "miscare" and p.a_miscat and not p.parcat and 0 < dt < 2:
                    self.harta.adauga(p.box, dt, *marime)
                self._sens_si_banda(p, t)
        self.harta.benzi.recalculeaza(t, *marime)
        self.harta.salveaza()
        return self.instantaneu()

    def _jurnal_camera(self):
        """Un fisier CSV pentru fiecare camera (dupa numele hartii ei)."""
        h = self.harta
        if h is self._harta_jurnal:
            return
        self.jurnal.scrie()
        self._harta_jurnal = h
        nume = os.path.splitext(os.path.basename(h.cale))[0] if h.cale else "camera"
        h.benzi.seteaza_fixe(self.benzi_fixe.get(nume))
        if h.benzi.fixe:
            print(f"Folosesc benzile desenate pentru camera '{nume}' ({len(h.benzi.fixe)} benzi).")
        director = os.path.join(AICI, "numaratori") if self.harti.dir is not None else None
        self.jurnal = JurnalMinut(director, nume)

    def _sens_si_banda(self, p, t):
        """Sens (spre intersectie / pleaca), banda, invatarea benzilor si numararea."""
        bz = self.harta.benzi
        x, y = (p.box[0] + p.box[2]) / 2, p.box[3]
        cat = p.categorie()
        if p.stare == "miscare" and p.directie is not None and not p.parcat:
            dy = p.directie[1]
            if abs(dy) >= 0.3:                     # merge clar in sus sau in jos pe imagine
                jos = dy > 0
                p.sens = 1 if jos == SETARI["sens_jos_intra"] else -1
            # invatam benzile din vehiculele care merg in lungul strazii (nu tramvaie)
            if p.a_miscat and cat == "masina" and p.sens is not None:
                if t - p._t_linie >= 1.5:
                    ist = [e for e in p.istoric if t - e[0] <= 3.0]
                    pts = np.array([((e[1] + e[3]) / 2, e[4]) for e in ist])
                    if len(pts) >= 4 and np.linalg.norm(pts[-1] - pts[0]) > 1.5 * p.inaltime():
                        bz.adauga_linie(pts)
                        p._t_linie = t
                if t - p._t_punct >= 0.5:
                    bz.adauga_punct(x, y, p.sens, p.directie)
                    p._t_punct = t
        if p.parcat:
            return
        if bz.fixe:
            b = bz.banda(x, y, p.sens, p.directie)
            if b is not None and p.stare == "miscare" and p.directie is not None \
                    and abs(p.directie[1]) >= 0.3:
                sens_mers = 1 if (p.directie[1] > 0) == SETARI["sens_jos_intra"] else -1
                if sens_mers != b[1]:
                    b = None                       # vireaza peste benzile celuilalt sens
            if b is not None:
                p.sens = b[1]                      # sensul benzii e cel sigur (desenat pe marcaje)
                p.banda = b                        # banda curenta (vehiculul poate schimba banda)
        else:
            if p.stare == "miscare" and p.directie is not None and not bz.pe_axa(x, y, p.directie):
                b = None                           # vireaza / traverseaza: fara banda
            else:
                b = bz.banda(x, y, p.sens, p.directie)
            if b is not None:
                p.benzi[b] += 1
                p.banda = p.benzi.most_common(1)[0][0]
                if p.sens is None:
                    p.sens = b[1]                  # oprit de la inceput: sensul benzii
        # numaram fiecare vehicul o singura data, cand e clar ca merge intr-un sens
        if not p.numarat and p.a_miscat and p.sens is not None and p.stare == "miscare":
            p.numarat = True
            tip = "intra" if p.sens == 1 else "iese"
            nb = bz.nume(p.banda) if p.banda and p.banda[1] == p.sens else None
            self.total[(tip, cat)] += 1
            self.total_banda[(tip, nb or "?")] += 1
            self.jurnal.cont[(tip, nb or "?", cat)] += 1

    def _analizeaza(self, p, t):
        S = SETARI
        W = S["fereastra_viteza"]
        ist = [e for e in p.istoric if t - e[0] <= W]
        if p.stare == "nou" and len(ist) < 3 and len(p.istoric) >= 2 and t - p.istoric[0][0] >= 1.0:
            ist = list(p.istoric)          # vazut rar (in afara zonei decupate): folosim tot istoricul
        if len(ist) >= 2 and ist[-1][0] - ist[0][0] >= 0.5 * W or (len(ist) >= 3 and ist[-1][0] - ist[0][0] >= 0.5 * W):
            n = max(1, len(ist) // 3)
            A = np.median(np.array([e[1:5] for e in ist[:n]]), 0)  # x1,y1,x2,y2 la inceput
            B = np.median(np.array([e[1:5] for e in ist[-n:]]), 0)  # ... la sfarsit
            mid = len(ist) // 2
            Mm = np.median(np.array([e[1:5] for e in ist[max(0, mid - n // 2):mid + n // 2 + 1]]), 0)
            dtw = max(np.mean([e[0] for e in ist[-n:]]) - np.mean([e[0] for e in ist[:n]]), 1e-3)
            ca = np.array([(A[0] + A[2]) / 2, (A[1] + A[3]) / 2])
            cb = np.array([(B[0] + B[2]) / 2, (B[1] + B[3]) / 2])
            # deplasarea centrului SI a marginii de jos (vehiculele care se departeaza de
            # camera se misca putin pe imagine, dar marginea de jos tot urca)
            dep = max(np.linalg.norm(cb - ca), abs(B[3] - A[3]))
            v = dep / dtw                                   # pixeli / secunda
            ref = min(B[2] - B[0], B[3] - B[1])            # marimea vehiculului
            prag_m = max(S["miscare_px"], S["miscare_rel"] * ref)
            prag_o = max(S["oprire_px"], S["oprire_rel"] * ref)
            if p.stare == "miscare":
                if v < prag_o:
                    p.stare = "oprit"
                    p.t_oprit = t
            else:
                # miscare reala = deplasare constanta in aceeasi directie (nu "tremurat" de chenar)
                cm = np.array([(Mm[0] + Mm[2]) / 2, (Mm[1] + Mm[3]) / 2])
                d1, d2 = cm - ca, cb - cm
                consecvent = (np.dot(d1, d2) > 0) or ((Mm[3] - A[3]) * (B[3] - Mm[3]) > 0)
                if v > prag_m and consecvent:
                    p.stare = "miscare"
                elif p.stare == "nou":
                    p.stare = "oprit"
                    p.t_oprit = p.t_start
            if p.stare == "miscare":
                d = cb - ca
                nd = np.linalg.norm(d)
                if nd > 0:
                    d = d / nd
                    p.directie = d if p.directie is None else (0.6 * p.directie + 0.4 * d)
                    p.directie = p.directie / (np.linalg.norm(p.directie) + 1e-9)
        h = p.inaltime()
        lung = max(p.box[2] - p.box[0], p.box[3] - p.box[1])
        p.parcurs = max(p.parcurs, np.linalg.norm(p.centru() - p.poz_start) / lung)
        if p.parcurs >= 1.0:
            p.a_miscat = True

        if p.parcat:
            if p.stare == "miscare" and np.linalg.norm(p.centru() - p.poz_parcare) / h > 0.7:
                p.parcat = False      # pleaca din parcare
                p.t_oprit = t
                p.poz_start, p.parcurs = p.centru(), 0.0
            return
        if p.stare != "oprit":
            return
        cat = p.categorie()
        if cat in TRANSPORT_COMUN:
            return  # autobuzele si tramvaiele nu sunt "parcate" (stau in statii)
        oprit_de = t - p.t_oprit
        z, W_, H_ = self.zone, *self.marime
        baza = ((p.box[0] + p.box[2]) / 2, p.box[3])
        if z.contine("parcare", baza) or self.harta.benzi.in_parcare(*baza):
            parcheaza = oprit_de >= S["parcat_zona_parcare"]
        elif cat not in TRANSPORT_COMUN and oprit_de >= S["parcat_dupa"]:
            parcheaza = True                       # nemiscat foarte mult timp
        elif z.contine("drum", baza):
            parcheaza = False                      # zona de drum desenata de utilizator
        elif self.harta.invatata():
            if self.harta.e_drum(p.box, W_, H_):
                parcheaza = False                  # oprit pe drum -> conteaza (semafor, coada)
            else:
                parcheaza = (not p.a_miscat and oprit_de >= S["parcat_afara_nemiscat"]) or \
                            oprit_de >= S["parcat_afara_oprit"]
        else:
            parcheaza = (not p.a_miscat and oprit_de >= S["parcat_harta_neinvatata"])
        if parcheaza:
            p.parcat = True
            p.poz_parcare = p.centru()

    def instantaneu(self):
        t = self.t
        elemente = []
        stat = Counter()
        dir_cnt = Counter()
        asteptare = Counter()     # banda -> vehicule oprite care asteapta sa intre
        sensuri = Counter()
        for p in self.urm.piste:
            if p.nr is None or t - p.t_ultim > 0.6:
                continue
            cat = p.categorie()
            b = tuple(int(v) for v in p.box)
            if p.parcat:
                stare = "parcat"
                stat["parcate"] += 1
            else:
                stare = p.stare
                if stare != "nou":
                    stat[(cat, stare)] += 1
            dir_idx = None
            if stare == "miscare" and p.directie is not None:
                ang = math.degrees(math.atan2(-p.directie[1], p.directie[0])) % 360
                dir_idx = int(((ang + 22.5) % 360) // 45)
                dir_cnt[dir_idx] += 1
            sec = int(t - p.t_oprit) if stare == "oprit" else 0
            poly = None if p.poligon is None else np.asarray(p.poligon).astype(int).tolist()
            banda = self.harta.benzi.nume(p.banda) if p.banda and p.banda[1] == p.sens else None
            asteapta = stare == "oprit" and p.sens == 1
            if asteapta:
                asteptare[banda or "?"] += 1
            if stare == "miscare" and p.sens is not None:
                sensuri["intra" if p.sens == 1 else "iese"] += 1
            elemente.append(dict(id=p.nr, box=b, poly=poly, cat=cat, stare=stare, sec=sec,
                                 dir=None if p.directie is None else tuple(p.directie),
                                 dir_idx=dir_idx, sens=p.sens, banda=banda, asteapta=asteapta))
        for cheie, n in asteptare.items():
            self.jurnal.asteapta_max[cheie] = max(self.jurnal.asteapta_max[cheie], n)
        bz = self.harta.benzi
        return dict(elemente=elemente, stat=stat, directii=dir_cnt, t=t,
                    harta_invatata=self.harta.invatata(), harta_min=self.harta.total / 60,
                    asteptare=asteptare, sensuri=sensuri, total=self.total,
                    total_banda=self.total_banda,
                    benzi=bz.rezumat() if bz.gata() else None,
                    benzi_linii=len(bz.linii))


def eticheta(e, unicode=True):
    if e["stare"] == "parcat":
        return "P"
    s = f"#{e['id']} {NUME_CAT[e['cat']]}"
    banda = f" {e['banda']}" if e.get("banda") else ""
    if e["stare"] == "oprit":
        s += (" ASTEAPTA" if e.get("asteapta") else " OPRIT") + f" {e['sec']}s{banda}"
    elif e["stare"] == "miscare":
        if e.get("sens") == 1:
            s += " INTRA" + banda
        elif e.get("sens") == -1:
            s += " IESE" + banda
        elif e["dir_idx"] is not None:
            s += " " + (SAGETI[e["dir_idx"]] if unicode else DIRECTII[e["dir_idx"]])
    return s


def culoare(e):
    if e["stare"] in ("parcat", "nou"):
        return CULORI[e["stare"]]
    return CULORI[(e["cat"], e["stare"])]


def text_statistici(inst, unicode=True):
    s = inst["stat"]
    r = []
    for cat, plural in (("masina", "Masini"), ("transport", "Transport in comun")):
        r.append(f"{plural}: {s[(cat, 'miscare')]} in miscare, {s[(cat, 'oprit')]} oprite")
    r.append(f"Parcate (ignorate): {s['parcate']}")
    sn = inst.get("sensuri", Counter())
    r.append(f"Acum: {sn['intra']} vin spre intersectie, {sn['iese']} pleaca")
    a = inst.get("asteptare", Counter())
    if a:
        detalii = "  ".join(f"{b}:{n}" for b, n in sorted(a.items()))
        r.append(f"Asteapta sa intre: {sum(a.values())}   ({detalii})")
    else:
        r.append("Asteapta sa intre: 0")
    tot = inst.get("total", Counter())
    if tot:
        ti = sum(n for (tip, _), n in tot.items() if tip == "intra")
        te = sum(n for (tip, _), n in tot.items() if tip == "iese")
        tb = inst.get("total_banda", Counter())
        pe_b = lambda tip: " ".join(f"{b}:{n}" for (t_, b), n in sorted(tb.items()) if t_ == tip and b != "?")
        r.append(f"Total intrate: {ti}  {pe_b('intra')}")
        r.append(f"Total iesite: {te}  {pe_b('iese')}")
    bz = inst.get("benzi")
    if bz:
        for nr, n_in, n_out in bz:
            nume_str = {"Bd": "Bulevard", "Dr": "Strada din dreapta"}.get(nr, f"Strada {nr}")
            pref = f"{nume_str}: " if len(bz) > 1 else "Benzi: "
            r.append(f"{pref}{n_in} benzi spre intersectie, {n_out} dinspre")
    elif "benzi_linii" in inst:
        r.append(f"Invat benzile... ({inst['benzi_linii']} traiectorii)")
    if not inst.get("harta_invatata", True):
        r.append(f"Invat drumul... ({inst.get('harta_min', 0) * 60 / 180 * 100:.0f}%)")
    return r


# ---------------------------------------------------------------------------
# Desenare pe imagine (mod fereastra / video)
# ---------------------------------------------------------------------------
def deseneaza(img, inst, zone=None, harta=None, arata_parcate=True, arata_zone=False, fps=None,
              arata_benzi=True):
    H, W = img.shape[:2]
    fs = max(0.4, W / 2600)
    th = 1 if W < 1600 else 2
    if arata_benzi and harta is not None:
        for tip, pts, col, txt in harta.benzi.desen(W, H):
            if tip == "linie":
                (xa, ya), (xb, yb) = pts
                cv2.line(img, (int(xa), int(ya)), (int(xb), int(yb)), hex_bgr(col), 1, cv2.LINE_AA)
            elif tip == "poligon":
                cv2.polylines(img, [np.array(pts, np.int32)], True, hex_bgr(col), 1, cv2.LINE_AA)
            else:
                (xa, ya), = pts
                cv2.putText(img, txt, (int(xa) - 15, int(ya)), cv2.FONT_HERSHEY_SIMPLEX, fs * 1.2,
                            hex_bgr(col), th + 1, cv2.LINE_AA)
    if arata_zone:
        if harta is not None:
            cv2.polylines(img, harta.contururi(W, H), True, hex_bgr(CULOARE_HARTA), 1, cv2.LINE_AA)
        if zone is not None:
            zone.pregateste(W, H)
            for tip, polis in zone.px.items():
                for poly in polis:
                    cv2.polylines(img, [poly.astype(np.int32)], True, hex_bgr(CULORI_ZONE[tip]), 1, cv2.LINE_AA)
    for e in inst["elemente"]:
        if e["stare"] == "parcat" and not arata_parcate:
            continue
        x1, y1, x2, y2 = e["box"]
        col = hex_bgr(culoare(e))
        gros = 1 if e["stare"] == "parcat" else th + 1
        if e["poly"] is not None:
            cv2.polylines(img, [np.array(e["poly"], np.int32)], True, col, gros, cv2.LINE_AA)
            x1, y1 = np.min(e["poly"], 0)
        else:
            cv2.rectangle(img, (x1, y1), (x2, y2), col, gros, cv2.LINE_AA)
        txt = eticheta(e, unicode=False)
        (tw, tht), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
        fundal = hex_bgr(CULORI["oprit_tag"]) if e["stare"] == "oprit" else col
        cv2.rectangle(img, (x1, y1 - tht - 6), (x1 + tw + 4, y1), fundal, -1)
        cv2.putText(img, txt, (x1 + 2, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0), th, cv2.LINE_AA)
        if e["stare"] == "miscare" and e["dir"] is not None:
            bx1, by1, bx2, by2 = e["box"]
            cx, cy = (bx1 + bx2) // 2, (by1 + by2) // 2
            L = 0.8 * max(bx2 - bx1, by2 - by1)
            cv2.arrowedLine(img, (cx, cy), (int(cx + e["dir"][0] * L), int(cy + e["dir"][1] * L)),
                            col, th + 1, cv2.LINE_AA, tipLength=0.3)
    linii = text_statistici(inst, unicode=False)
    if fps is not None:
        linii.insert(0, f"FPS analiza: {fps:.1f}")
    lh = int(26 * fs / 0.5)
    cv2.rectangle(img, (0, 0), (int(560 * fs / 0.5), lh * len(linii) + 10), (0, 0, 0), -1)
    for i, l in enumerate(linii):
        cv2.putText(img, l, (8, lh * (i + 1)), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), th, cv2.LINE_AA)
    return img


# ---------------------------------------------------------------------------
# Detector (ultralytics): YOLOE cu cuvinte (are "tram") sau YOLO clasic (COCO)
# ---------------------------------------------------------------------------
class DetectorYOLO:
    def __init__(self, model=MODEL_IMPLICIT, imgsz=960, device=None, openvino=None):
        from ultralytics import YOLO
        try:
            import torch
            cuda = torch.cuda.is_available() and device != "cpu"
        except Exception:
            cuda = False
        if openvino is None:                      # automat: OpenVINO cand nu e placa NVIDIA
            openvino = not cuda
        stem = os.path.splitext(os.path.basename(model))[0]
        e_yoloe = "yoloe" in stem.lower()
        dir_ov = os.path.join(AICI, stem + "_openvino_dinamic")
        m = None
        if openvino and os.path.isdir(dir_ov):
            m = self._incarca_openvino(dir_ov, model)
        if m is None:
            if e_yoloe:
                from ultralytics import YOLOE
                m = YOLOE(model)
                cache = os.path.join(AICI, f"prompturi_{stem}.npz")
                incarcat = False
                if os.path.exists(cache):
                    try:
                        m.load_prompt_embeddings(cache)
                        incarcat = list(m.names.values() if isinstance(m.names, dict) else m.names) == PROMPTURI
                    except Exception:
                        incarcat = False
                if not incarcat:
                    print("Prima pornire: pregatesc cuvintele (descarca ~250 MB o singura data)...")
                    m.set_classes(PROMPTURI)
                    try:
                        m.save_prompt_embeddings(cache)
                    except Exception:
                        pass
            else:
                m = YOLO(model)
            if openvino:
                try:
                    print("Optimizez modelul pentru procesor cu OpenVINO (doar prima data, 1-3 min)...")
                    iesire = m.export(format="openvino", dynamic=True, half=False, imgsz=imgsz)
                    if os.path.abspath(str(iesire)) != dir_ov:
                        if os.path.isdir(dir_ov):
                            import shutil
                            shutil.rmtree(dir_ov)
                        os.replace(str(iesire), dir_ov)
                    m_ov = self._incarca_openvino(dir_ov, model)
                    if m_ov is not None:
                        m = m_ov
                except Exception as ex:
                    print(f"OpenVINO nu a mers ({ex!r}); continui fara.")
        self.m = m
        nume = m.names if isinstance(m.names, dict) else dict(enumerate(m.names))
        self.id_cat = {int(i): NUME_LA_CAT[n] for i, n in nume.items() if n in NUME_LA_CAT}
        self.clase = sorted(self.id_cat)
        if e_yoloe:
            SETARI["conf_min"], SETARI["conf_nou"] = 0.10, 0.25
        self.imgsz = imgsz
        self.device = device
        self.half = bool(cuda) and not self.ov
        if self.ov:
            print("Rulez cu OpenVINO pe " + ("placa video Intel." if "gpu" in self.ov_device else "procesor."))
        elif cuda:
            import torch
            print(f"Rulez pe placa video: {torch.cuda.get_device_name(0)} (FP16)")
        else:
            print("Rulez pe procesor (CPU). Daca e lent: --model yoloe-26n-seg.pt --imgsz 640")

    ov = False

    ov_device = "intel:cpu"

    def _incarca_openvino(self, dir_ov, model):
        """Incarca modelul OpenVINO pe cel mai rapid dispozitiv: placa video Intel sau procesorul."""
        from ultralytics import YOLO
        task = "segment" if "seg" in model else "detect"
        try:
            import openvino as ov
            disp = ov.Core().available_devices
        except Exception:
            disp = ["CPU"]
        candidati = (["intel:gpu"] if any(d.startswith("GPU") for d in disp) else []) + ["intel:cpu"]
        test = np.random.randint(0, 255, (544, 960, 3), np.uint8)
        cel_mai_bun, timp_min = None, float("inf")
        for dev in candidati:
            try:
                m = YOLO(dir_ov, task=task)
                for _ in range(2):
                    m.predict(test, imgsz=640, device=dev, verbose=False)  # incalzire / compilare
                t0 = time.time()
                for _ in range(4):
                    m.predict(test, imgsz=640, device=dev, verbose=False)
                dt = (time.time() - t0) / 4
                print(f"  OpenVINO pe {'placa video Intel' if 'gpu' in dev else 'procesor'}: {1 / dt:.1f} cadre/s")
                if dt < timp_min:
                    cel_mai_bun, timp_min, self.ov_device = m, dt, dev
            except Exception as ex:
                print(f"  {dev} nu merge: {ex!r}")
        if cel_mai_bun is None:
            print("Nu pot folosi modelul OpenVINO; continui fara.")
            return None
        self.ov = True
        return cel_mai_bun

    def __call__(self, frame, imgsz=None):
        kw = dict(imgsz=imgsz or self.imgsz, conf=SETARI["conf_min"], classes=self.clase,
                  agnostic_nms=True, verbose=False)
        if self.ov:
            kw["device"] = self.ov_device
        elif self.device is not None:
            kw["device"] = self.device
        if self.half:
            kw["half"] = True
        r = self.m.predict(frame, **kw)[0]
        b = r.boxes
        cls = b.cls.cpu().numpy().astype(int)
        cats = [self.id_cat.get(int(c), "masina") for c in cls]
        polys = None
        if r.masks is not None:
            polys = [simplifica_contur(p) for p in r.masks.xy]
        return b.xyxy.cpu().numpy(), b.conf.cpu().numpy(), cats, polys


class DetectorDecupat:
    """Trimite la model doar zona cu drum (invatata). Aceeasi finete, mult mai putini pixeli."""

    LA_FIECARE = 8   # la fiecare al 8-lea cadru analizam toata imaginea (gasim drumuri noi)

    def __init__(self, detector, analizor, zone, imgsz, detaliu=960, fps_tinta=8.0, decupare=True,
                 rez_minima=512):
        self.det, self.an, self.zone = detector, analizor, zone
        self.imgsz_max = imgsz            # rezolutia maxima trimisa la model
        self.imgsz = imgsz                # rezolutia curenta (scade automat daca merge greu)
        self.detaliu = detaliu            # finetea dorita, ca pe o imagine intreaga la 'detaliu' px
        self.fps_tinta = fps_tinta
        self.decupare = decupare
        # sub rez_minima masinile mici nu mai sunt vazute; daca e mai mare ca imgsz, urcam si maximul
        self.rez_minima = int(rez_minima)
        if self.rez_minima > self.imgsz_max:
            self.imgsz_max = self.imgsz = self.rez_minima
        print(f"Rezolutie analiza: pornesc la {self.imgsz}, minima {self.rez_minima}, "
              f"tinta {fps_tinta:g} cadre/s")
        self.roi_curent = None
        self.n = 0
        self._timpi = deque(maxlen=30)
        self._t_ajustare = time.time()

    def _ajusteaza(self, durata):
        """Rezolutie adaptiva: coboram pana atingem fps-ul tinta, urcam daca e rezerva."""
        self._timpi.append(durata)
        if time.time() - self._t_ajustare < 4 or len(self._timpi) < 5:
            return
        self._t_ajustare = time.time()
        fps = 1.0 / max(np.median(self._timpi), 1e-3)
        vechi = self.imgsz
        if fps < 0.9 * self.fps_tinta and self.imgsz > self.rez_minima:
            self.imgsz = max(self.rez_minima, self.imgsz - (128 if fps < 0.6 * self.fps_tinta else 64))
            if self.imgsz == self.rez_minima:
                print(f"Am ajuns la rezolutia minima {self.rez_minima}; nu cobor mai jos ca sa nu pierd "
                      "masinile mici. Pentru mai multa viteza: --model yoloe-26n-seg.pt")
        elif fps > 1.6 * self.fps_tinta and self.imgsz < self.imgsz_max:
            self.imgsz = min(self.imgsz_max, self.imgsz + 64)
        if self.imgsz != vechi:
            self._timpi.clear()
            print(f"Rezolutie analiza: {vechi} -> {self.imgsz} (detectie {fps:.1f} cadre/s, tinta {self.fps_tinta:g})")

    def __call__(self, frame):
        H, W = frame.shape[:2]
        self.n += 1
        t0 = time.time()
        r = self.an.harta.roi(W, H, self.zone) if self.decupare else None
        if self.n % self.LA_FIECARE == 0:
            r = None
        self.roi_curent = r
        if r is None:
            rez = self.det(frame, imgsz=self.imgsz)
            self._ajusteaza(time.time() - t0)
            return rez
        x1, y1, x2, y2 = r
        decupaj = frame[y1:y2, x1:x2]
        # finetea dorita pe zona decupata, la multiplu de 64, fara sa depasim rezolutia curenta
        scara = self.detaliu / max(W, H)
        imgsz = int(min(self.imgsz, round(max(x2 - x1, y2 - y1) * scara / 64) * 64))
        # nici pe zona decupata nu coboram sub minim (dar nici nu marim peste marimea ei reala)
        imgsz = max(imgsz, min(self.rez_minima, int(math.ceil(max(x2 - x1, y2 - y1) / 64) * 64)), 320)
        b, c, k, pl = self.det(decupaj, imgsz=imgsz)
        self._ajusteaza(time.time() - t0)
        if len(b):
            b = b + np.array([x1, y1, x1, y1], np.float32)
        if pl is not None:
            pl = [None if p is None else p + np.array([x1, y1]) for p in pl]
        return b, c, k, pl


def creeaza_detector(a):
    try:
        return DetectorYOLO(a.model, a.imgsz, a.device, a.openvino)
    except Exception as ex:
        if a.model == MODEL_REZERVA:
            raise
        print(f"\nNu am putut porni modelul {a.model}: {ex!r}")
        print(f"Folosesc modelul clasic {MODEL_REZERVA} (fara clasa 'tramvai').\n")
        return DetectorYOLO(MODEL_REZERVA, a.imgsz, a.device, a.openvino)


# ---------------------------------------------------------------------------
# Surse de imagine
# ---------------------------------------------------------------------------
def regiune_ecran(cfg):
    import mss
    with mss.mss() as sct:
        mon_idx = int(cfg.get("monitor", 1))
        mon_idx = mon_idx if mon_idx < len(sct.monitors) else 1
        mon = sct.monitors[mon_idx]
    r = cfg.get("regiune")
    if r:
        return dict(left=int(r[0]), top=int(r[1]), width=int(r[2]), height=int(r[3]))
    return dict(left=mon["left"], top=mon["top"], width=mon["width"], height=mon["height"])


class SursaEcran:
    def __init__(self, regiune, fps_max=15):
        self.reg = regiune
        self.perioada = 1.0 / fps_max
        self.sct = None
        self._ultim = 0

    def citeste(self):
        import mss
        if self.sct is None:
            self.sct = mss.mss()  # creat in firul care il foloseste
        astept = self.perioada - (time.time() - self._ultim)
        if astept > 0:
            time.sleep(astept)
        self._ultim = time.time()
        img = np.asarray(self.sct.grab(self.reg))
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR), time.time()


class SursaVideo:
    def __init__(self, cale, fps_analiza=10, start=0.0, durata=None):
        self.cap = cv2.VideoCapture(cale)
        if not self.cap.isOpened():
            raise SystemExit(f"Nu pot deschide {cale}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.pas = max(1, round(self.fps / fps_analiza))
        self.i = int(start * self.fps)
        self.stop = None if durata is None else self.i + int(durata * self.fps)
        if self.i:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.i)

    def citeste(self):
        if self.stop is not None and self.i >= self.stop:
            return None, None
        ok, f = self.cap.read()
        if not ok:
            return None, None
        t = self.i / self.fps
        for _ in range(self.pas - 1):
            self.cap.grab()
        self.i += self.pas
        return f, t


# ---------------------------------------------------------------------------
# Configurare interactiva (zona de ecran + zone optionale)
# ---------------------------------------------------------------------------
def incarca_benzi_fixe():
    """benzi_fixe.json: {nume_camera: [ {strada, sens, nr, poligon}, ... ]}"""
    cale = os.path.join(AICI, "benzi_fixe.json")
    if os.path.exists(cale):
        try:
            with open(cale, encoding="utf-8") as f:
                return json.load(f)
        except Exception as ex:
            print("Nu pot citi benzi_fixe.json:", ex)
    return {}


def incarca_config(cale):
    if os.path.exists(cale):
        with open(cale, encoding="utf-8") as f:
            return json.load(f)
    return {"monitor": 1, "regiune": None, "zone": {}}


def salveaza_config(cale, cfg):
    with open(cale, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1, ensure_ascii=False)
    print(f"Configuratie salvata: {cale}")


def _incape(img, maxw=1500, maxh=850):
    h, w = img.shape[:2]
    s = min(maxw / w, maxh / h, 1.0)
    return cv2.resize(img, (int(w * s), int(h * s))) if s < 1 else img.copy(), s


def editor_zone(img, zone_existente):
    vis0, s = _incape(img)
    H, W = vis0.shape[:2]
    zone = {k: [list(p) for p in zone_existente.get(k, [])] for k in ("drum", "tramvai", "parcare")}
    curent, mod = [], "parcare"
    taste = {ord("d"): "drum", ord("t"): "tramvai", ord("p"): "parcare"}
    fer = "Zone optionale - vezi instructiunile din imagine"

    def inchide():
        nonlocal curent
        if len(curent) >= 3:
            zone[mod].append(curent)
        curent = []

    def mouse(ev, x, y, *_):
        if ev == cv2.EVENT_LBUTTONDOWN:
            curent.append([round(x / W, 4), round(y / H, 4)])
        elif ev == cv2.EVENT_RBUTTONDOWN:
            inchide()

    cv2.namedWindow(fer)
    cv2.setMouseCallback(fer, mouse)
    instr = [
        "OPTIONAL - drumul se invata singur. Apasa s daca nu vrei sa desenezi nimic.",
        "Click stanga = punct | Click dreapta / Enter = inchide poligonul",
        "p = PARCARE (masinile oprite aici = parcate)   d = DRUM (aici oprit = in trafic)",
        "t = TRAMVAI (doar pt. modelul clasic)   z = anuleaza  c = sterge  s = SALVEAZA  Esc = renunta",
    ]
    while True:
        vis = vis0.copy()
        strat = vis.copy()
        for tip, polis in zone.items():
            for p in polis:
                pts = (np.array(p) * [W, H]).astype(np.int32)
                cv2.fillPoly(strat, [pts], hex_bgr(CULORI_ZONE[tip]))
                cv2.polylines(vis, [pts], True, hex_bgr(CULORI_ZONE[tip]), 2)
        vis = cv2.addWeighted(strat, 0.25, vis, 0.75, 0)
        if curent:
            pts = (np.array(curent) * [W, H]).astype(np.int32)
            cv2.polylines(vis, [pts], False, hex_bgr(CULORI_ZONE[mod]), 2)
            for q in pts:
                cv2.circle(vis, tuple(int(v) for v in q), 4, (255, 255, 255), -1)
        cv2.rectangle(vis, (0, 0), (W, 22 * (len(instr) + 1) + 6), (0, 0, 0), -1)
        for i, l in enumerate(instr):
            cv2.putText(vis, l, (8, 20 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(vis, f"MOD CURENT: {mod.upper()}", (8, 20 + 22 * len(instr)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, hex_bgr(CULORI_ZONE[mod]), 2, cv2.LINE_AA)
        cv2.imshow(fer, vis)
        k = cv2.waitKey(30) & 0xFF
        if k in taste:
            inchide()
            mod = taste[k]
        elif k in (13, 10, 32):
            inchide()
        elif k == ord("z"):
            if curent:
                curent.pop()
            elif zone[mod]:
                zone[mod].pop()
        elif k == ord("c"):
            zone[mod], curent = [], []
        elif k == ord("s"):
            inchide()
            cv2.destroyWindow(fer)
            return zone
        elif k == 27:
            cv2.destroyWindow(fer)
            return None
        if cv2.getWindowProperty(fer, cv2.WND_PROP_VISIBLE) < 1:
            return None


def configurare(cale_cfg, video=None):
    cfg = incarca_config(cale_cfg)
    if video:
        cap = cv2.VideoCapture(video)
        ok, img = cap.read()
        if not ok:
            raise SystemExit("Nu pot citi videoclipul")
    else:
        import mss
        with mss.mss() as sct:
            mon_idx = int(cfg.get("monitor", 1))
            mon = sct.monitors[mon_idx if mon_idx < len(sct.monitors) else 1]
            print("Peste 2 secunde fac o captura de ecran. Lasa vizibil stream-ul camerei...")
            time.sleep(2)
            ecran = cv2.cvtColor(np.asarray(sct.grab(mon)), cv2.COLOR_BGRA2BGR)
        vis, s = _incape(ecran)
        print("Trage un dreptunghi peste imaginea camerei, apoi Enter. (Enter fara selectie = tot ecranul)")
        x, y, w, h = cv2.selectROI("Selecteaza imaginea camerei + Enter", vis, showCrosshair=False)
        cv2.destroyAllWindows()
        if w > 10 and h > 10:
            X, Y, Wd, Hd = int(x / s), int(y / s), int(w / s), int(h / s)
            cfg["regiune"] = [mon["left"] + X, mon["top"] + Y, Wd, Hd]
            img = ecran[Y:Y + Hd, X:X + Wd]
        else:
            cfg["regiune"] = None
            img = ecran
    zone = editor_zone(img, cfg.get("zone", {}))
    if zone is None:
        print("Renuntat - nimic salvat.")
        return
    cfg["zone"] = zone
    salveaza_config(cale_cfg, cfg)


# ---------------------------------------------------------------------------
# Overlay transparent peste ecran (Windows)
# ---------------------------------------------------------------------------
class Motor(threading.Thread):
    """Fir de lucru: captura -> detectie -> urmarire -> analiza."""

    def __init__(self, sursa, detector, analizor):
        super().__init__(daemon=True)
        self.sursa, self.det, self.an = sursa, detector, analizor
        self.lacat = threading.Lock()
        self.ultim = None
        self.versiune = 0
        self.fps = 0.0
        self.oprit = False
        self.eroare = None

    def run(self):
        try:
            while not self.oprit:
                t0 = time.time()
                frame, t = self.sursa.citeste()
                if frame is None:
                    break
                self.an.observa_cadru(frame, t)
                b, c, k, pl = self.det(frame)
                inst = self.an.actualizeaza(b, c, k, pl, t, (frame.shape[1], frame.shape[0]))
                dt = time.time() - t0
                self.fps = 0.8 * self.fps + 0.2 * (1 / max(dt, 1e-3)) if self.fps else 1 / max(dt, 1e-3)
                with self.lacat:
                    self.ultim = inst
                    self.versiune += 1
        except Exception as ex:  # afisam eroarea in panou
            self.eroare = repr(ex)
            raise


def _win_exclude_din_captura(hwnd, click_prin=False):
    import ctypes
    u32 = ctypes.windll.user32
    if click_prin:
        GWL_EXSTYLE = -20
        stil = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        stil |= 0x80000 | 0x20 | 0x80 | 0x08000000  # LAYERED|TRANSPARENT|TOOLWINDOW|NOACTIVATE
        u32.SetWindowLongW(hwnd, GWL_EXSTYLE, stil)
    WDA_EXCLUDEFROMCAPTURE = 0x11
    return bool(u32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))


class Overlay:
    CHEIE = "#010203"  # culoarea care devine transparenta

    def __init__(self, motor, regiune, zone, analizor):
        import tkinter as tk
        import tkinter.font as tkfont
        import ctypes
        self.tk = tk
        self.motor, self.zone, self.an = motor, zone, analizor
        x, y, w, h = regiune["left"], regiune["top"], regiune["width"], regiune["height"]
        self.w, self.h = w, h
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.configure(bg=self.CHEIE)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", self.CHEIE)
        self.cv = tk.Canvas(self.root, width=w, height=h, bg=self.CHEIE, highlightthickness=0)
        self.cv.pack()
        self.font = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.root.update_idletasks()
        hwnd = ctypes.windll.user32.GetAncestor(self.root.winfo_id(), 2)
        self.exclus = _win_exclude_din_captura(hwnd, click_prin=True)
        if not self.exclus:
            print("ATENTIE: Windows nu permite excluderea overlay-ului din captura "
                  "(e nevoie de Windows 10 2004+). Contururile pot fi 'vazute' de detector. "
                  "Foloseste --mod fereastra daca apar probleme.")

        # panou de control
        self.panou = tk.Toplevel(self.root)
        self.panou.title("Detector intersectie")
        self.panou.attributes("-topmost", True)
        self.panou.geometry(f"+{x + 20}+{y + 60}")
        self.panou.configure(bg="#1b1b1b")
        self.lbl = tk.Label(self.panou, text="Pornesc modelul...", justify="left", anchor="w",
                            font=("Segoe UI", 10), fg="white", bg="#1b1b1b", padx=10, pady=8)
        self.lbl.pack(fill="x")
        self.v_parcate = tk.BooleanVar(value=True)
        self.v_zone = tk.BooleanVar(value=False)
        self.v_benzi = tk.BooleanVar(value=True)
        self.v_ascuns = tk.BooleanVar(value=False)
        for txt, var in (("Arata masinile parcate (gri)", self.v_parcate),
                         ("Arata drumul invatat", self.v_zone),
                         ("Arata benzile", self.v_benzi),
                         ("Ascunde contururile", self.v_ascuns)):
            tk.Checkbutton(self.panou, text=txt, variable=var, fg="white", bg="#1b1b1b",
                           selectcolor="#333", activebackground="#1b1b1b", activeforeground="white",
                           command=self._forteaza).pack(anchor="w", padx=8)
        tk.Button(self.panou, text="Opreste", command=self.inchide, bg="#a01818", fg="white",
                  relief="flat", padx=12).pack(pady=8)
        self.panou.protocol("WM_DELETE_WINDOW", self.inchide)
        self.panou.update_idletasks()
        _win_exclude_din_captura(ctypes.windll.user32.GetAncestor(self.panou.winfo_id(), 2))
        self.vers_desenata = -1
        self._ultim_lift = time.time()
        self.root.after(50, self._bucla)

    def _forteaza(self):
        self.vers_desenata = -1

    def inchide(self):
        self.motor.oprit = True
        self.an.harta.salveaza(fortat=True)
        self.an.jurnal.scrie()
        self.root.destroy()

    def _bucla(self):
        with self.motor.lacat:
            inst, vers = self.motor.ultim, self.motor.versiune
        if inst is not None and vers != self.vers_desenata:
            self.vers_desenata = vers
            self._deseneaza(inst)
            rez = getattr(getattr(self.motor, "det", None), "imgsz", None)
            linii = [f"FPS analiza: {self.motor.fps:.1f}" + (f"  (rezolutie {rez})" if rez else "")] \
                + text_statistici(inst)
            self.lbl.config(text="\n".join(linii))
        if self.motor.eroare:
            self.lbl.config(text="EROARE:\n" + self.motor.eroare, fg="#ff6060")
        if time.time() - self._ultim_lift > 3:  # ramanem deasupra browserului
            self._ultim_lift = time.time()
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.panou.lift()
        self.root.after(30, self._bucla)

    def _deseneaza(self, inst):
        cv = self.cv
        cv.delete("all")
        if self.v_ascuns.get():
            return
        if self.v_benzi.get():
            for tip, pts, col, txt in self.an.harta.benzi.desen(self.w, self.h):
                if tip == "linie":
                    cv.create_line(*[v for q in pts for v in q], fill=col, width=2, dash=(8, 6))
                elif tip == "poligon":
                    cv.create_polygon(*[v for q in pts for v in q], outline=col, fill="", width=2,
                                      dash=(8, 6))
                else:
                    (xa, ya), = pts
                    cv.create_text(xa, ya, text=txt, fill=col, font=("Segoe UI", 14, "bold"))
        if self.v_zone.get():
            for c in self.an.harta.contururi(self.w, self.h):
                if len(c) >= 3:
                    cv.create_polygon(*c.flatten().tolist(), outline=CULOARE_HARTA, fill="", width=2)
            self.zone.pregateste(self.w, self.h)
            for tip, polis in self.zone.px.items():
                for p in polis:
                    cv.create_polygon(*p.flatten().tolist(), outline=CULORI_ZONE[tip], fill="",
                                      dash=(6, 4), width=2)
        for e in inst["elemente"]:
            if e["stare"] == "parcat" and not self.v_parcate.get():
                continue
            x1, y1, x2, y2 = e["box"]
            col = culoare(e)
            parcat = e["stare"] == "parcat"
            if e["poly"] is not None:
                pts = [v for q in e["poly"] for v in q]
                cv.create_polygon(*pts, outline=col, fill="", width=1 if parcat else 3,
                                  dash=(3, 3) if parcat else None)
                lx, ly = min(q[0] for q in e["poly"]), min(q[1] for q in e["poly"])
            else:
                cv.create_rectangle(x1, y1, x2, y2, outline=col, width=1 if parcat else 3,
                                    dash=(3, 3) if parcat else None)
                lx, ly = x1, y1
            if parcat:
                continue
            txt = eticheta(e)
            tw = self.font.measure(txt) + 6
            fundal = CULORI["oprit_tag"] if e["stare"] == "oprit" else col
            cv.create_rectangle(lx, ly - 17, lx + tw, ly, fill=fundal, outline=fundal)
            cv.create_text(lx + 3, ly - 9, text=txt, anchor="w", font=self.font,
                           fill="white" if e["stare"] == "oprit" else "black")
            if e["stare"] == "miscare" and e["dir"] is not None:
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                L = 0.8 * max(x2 - x1, y2 - y1)
                cv.create_line(cx, cy, cx + e["dir"][0] * L, cy + e["dir"][1] * L, fill=col,
                               width=3, arrow=self.tk.LAST, arrowshape=(12, 14, 5))

    def ruleaza(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def dpi_aware():
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def ruleaza_bucla_simpla(sursa, detector, analizor, zone, afiseaza=True, salveaza=None, titlu="Detector"):
    """Mod fereastra / fisier video: o singura bucla, imaginea adnotata in fereastra OpenCV."""
    scriitor = None
    arata_parcate, arata_zone = True, False
    fps = 0.0
    try:
        while True:
            t0 = time.time()
            frame, t = sursa.citeste()
            if frame is None:
                break
            analizor.observa_cadru(frame, t)
            b, c, k, pl = detector(frame)
            inst = analizor.actualizeaza(b, c, k, pl, t, (frame.shape[1], frame.shape[0]))
            dt = time.time() - t0
            fps = 0.8 * fps + 0.2 / max(dt, 1e-3) if fps else 1 / max(dt, 1e-3)
            out = deseneaza(frame, inst, zone, analizor.harta, arata_parcate, arata_zone, fps)
            if salveaza:
                if scriitor is None:
                    fps_out = getattr(sursa, "fps", 30) / getattr(sursa, "pas", 1)
                    scriitor = cv2.VideoWriter(salveaza, cv2.VideoWriter_fourcc(*"mp4v"), fps_out,
                                               (out.shape[1], out.shape[0]))
                scriitor.write(out)
            if afiseaza:
                vis, _ = _incape(out, 1600, 900)
                cv2.imshow(titlu + "  (q = iesire, p = parcate, z = drum invatat)", vis)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord("p"):
                    arata_parcate = not arata_parcate
                if key == ord("z"):
                    arata_zone = not arata_zone
    finally:
        analizor.harta.salveaza(fortat=True)
        analizor.jurnal.scrie()
        if scriitor:
            scriitor.release()
            print(f"Salvat: {salveaza}")
        if afiseaza:
            cv2.destroyAllWindows()


def main():
    ap = argparse.ArgumentParser(description="Detector live de vehicule in intersectie")
    ap.add_argument("--configurare", action="store_true", help="alege zona de ecran (+ zone optionale)")
    ap.add_argument("--config", default=CONFIG_IMPLICIT)
    ap.add_argument("--mod", choices=["overlay", "fereastra"], default=None,
                    help="overlay = contururi direct pe ecran (implicit pe Windows); fereastra = fereastra separata")
    ap.add_argument("--video", help="analizeaza un fisier video in loc de ecran")
    ap.add_argument("--salveaza", help="salveaza videoclipul adnotat (cu --video)")
    ap.add_argument("--model", default=MODEL_IMPLICIT,
                    help="yoloe-26s-seg.pt (implicit, recunoaste tramvaie) / yoloe-26n-seg.pt (rapid) / "
                         "yoloe-26m-seg.pt (precis) / yolo11s-seg.pt (clasic)")
    ap.add_argument("--imgsz", type=int, default=640,
                    help="rezolutia maxima trimisa la model (scade automat daca nu se atinge --fps-tinta)")
    ap.add_argument("--detaliu", type=int, default=960,
                    help="finetea dorita pe zona cu drum (mai mare = vede masini mai mici)")
    ap.add_argument("--fps-tinta", type=float, default=8.0, help="cadre/s dorite; rezolutia se adapteaza")
    ap.add_argument("--rez-minima", type=int, default=512,
                    help="rezolutia sub care nu coboara niciodata (implicit 512)")
    ap.add_argument("--device", default=None, help="cpu, 0 (placa NVIDIA)... implicit automat")
    ap.add_argument("--openvino", dest="openvino", action="store_true", default=None,
                    help="forteaza OpenVINO (implicit: automat cand nu ai placa NVIDIA)")
    ap.add_argument("--fara-openvino", dest="openvino", action="store_false")
    ap.add_argument("--fara-decupare", action="store_true",
                    help="analizeaza toata imaginea, nu doar zona cu drum")
    ap.add_argument("--fps-max", type=float, default=15)
    ap.add_argument("--monitor", type=int, default=None, help="numarul monitorului (1 = principal)")
    ap.add_argument("--parcat-dupa", type=float, default=SETARI["parcat_dupa"],
                    help="secunde nemiscat dupa care o masina e considerata parcata (implicit 120)")
    ap.add_argument("--inverseaza-sensul", action="store_true",
                    help="cine URCA pe imagine vine spre intersectie (implicit: cine coboara)")
    ap.add_argument("--reseteaza-benzi", action="store_true",
                    help="uita benzile invatate pentru camera curenta (drumul ramane)")
    ap.add_argument("--reseteaza-harta", action="store_true",
                    help="uita drumul invatat pentru camera curenta si invata din nou")
    a = ap.parse_args()
    SETARI["parcat_dupa"] = a.parcat_dupa
    SETARI["sens_jos_intra"] = not a.inverseaza_sensul

    dpi_aware()
    if a.configurare:
        if a.monitor:
            cfg = incarca_config(a.config)
            cfg["monitor"] = a.monitor
            salveaza_config(a.config, cfg)
        configurare(a.config, a.video)
        return

    cfg = incarca_config(a.config)
    if a.monitor:
        cfg["monitor"] = a.monitor
    zone = Zone(cfg.get("zone"))
    harti = ManagerHarti(DIR_HARTI, reseteaza=a.reseteaza_harta, reseteaza_benzi=a.reseteaza_benzi)

    print(f"Incarc modelul {a.model} ...")
    detector = creeaza_detector(a)
    analizor = Analizor(zone, harti, incarca_benzi_fixe())
    detector = DetectorDecupat(detector, analizor, zone, a.imgsz, a.detaliu, a.fps_tinta,
                               decupare=not a.fara_decupare, rez_minima=a.rez_minima)

    if a.video:
        ruleaza_bucla_simpla(SursaVideo(a.video), detector, analizor, zone, True, a.salveaza, a.video)
        return

    reg = regiune_ecran(cfg)
    print(f"Captez ecranul: {reg}")
    mod = a.mod or ("overlay" if sys.platform == "win32" else "fereastra")
    sursa = SursaEcran(reg, a.fps_max)
    if mod == "fereastra":
        print("Muta fereastra de rezultat pe alt monitor sau langa stream (sa nu acopere camera).")
        ruleaza_bucla_simpla(sursa, detector, analizor, zone, True, None, "Detector live")
        return
    motor = Motor(sursa, detector, analizor)
    ov = Overlay(motor, reg, zone, analizor)
    motor.start()
    print("Ruleaza. Inchide din panoul 'Detector intersectie' (butonul Opreste).")
    try:
        ov.ruleaza()
    finally:
        motor.oprit = True
        analizor.harta.salveaza(fortat=True)
        analizor.jurnal.scrie()


if __name__ == "__main__":
    main()
