# Semafoare AI — Plan de implementare IT

Versiune: 17.10.2026 · Intersecția de lucru: **Piața Unirii, Iași** (camera WebcamRomania de pe Grand Hotel Traian)

## Cuprins

0. [Decizii fixate](#0-decizii-fixate)
1. [Scop și principii](#1-scop-și-principii)
2. [Arhitectura generală](#2-arhitectura-generală)
3. [Stack tehnologic și versiuni](#3-stack-tehnologic-și-versiuni)
4. [Structura proiectului și configurarea](#4-structura-proiectului-și-configurarea)
5. [Contracte de date](#5-contracte-de-date)
6. [Modulul 1 — Harta Piața Unirii și scenariul de trafic](#6-modulul-1--harta-piața-unirii-și-scenariul-de-trafic)
7. [Modulul 2 — Mediul RL și antrenarea AI](#7-modulul-2--mediul-rl-și-antrenarea-ai)
8. [Modulul 3 — Controlere și evaluare](#8-modulul-3--controlere-și-evaluare)
9. [Modulul 4 — Motorul de simulare cu geamăn](#9-modulul-4--motorul-de-simulare-cu-geamăn)
10. [Modulul 5 — Serverul FastAPI și puntea serială](#10-modulul-5--serverul-fastapi-și-puntea-serială)
11. [Modulul 6 — Frontend-ul (dashboard)](#11-modulul-6--frontend-ul-dashboard)
12. [Modulul 7 — Percepția video din webcam-ul Piața Unirii](#12-modulul-7--percepția-video-din-webcam-ul-piața-unirii)
13. [Contractul cu firmware-ul ESP32](#13-contractul-cu-firmware-ul-esp32)
14. [Plan de lucru pe etape și ore](#14-plan-de-lucru-pe-etape-și-ore)
15. [Testare, scenariul demo și planuri de rezervă](#15-testare-scenariul-demo-și-planuri-de-rezervă)
16. [Riscuri și întrebări de la juriu](#16-riscuri-și-întrebări-de-la-juriu)
17. [Faza 2](#17-faza-2)
18. [Cum dezvoltați cu Claude](#18-cum-dezvoltați-cu-claude)
- [Anexa A — `vision/zones.json` inițial](#anexa-a--visionzonesjson-inițial)
- [Anexa B — Email către WebcamRomania](#anexa-b--email-către-webcamromania)

---

## 0. Decizii fixate

| Decizie | Alegere |
| --- | --- |
| Intersecția modelată | Piața Unirii, Iași: bulevardul cu linie de tramvai × strada laterală din dreapta cadrului, cu trecerea de pietoni (A) + următoarea intersecție semaforizată pe bulevard (B) |
| Comparația | două simulări SUMO în paralel, același trafic și seed: clasic (program fix) vs AI |
| Controler AI | PPO cu politică partajată; max-pressure ca pornire și plan B |
| Sursa „ochilor reali” | webcam-ul public din Piața Unirii (cu acordul WebcamRomania), plus clip înregistrat ca rezervă |
| Legătura cu placa | serial USB 115200, heartbeat cu contor, ACK de la placă; ESP32 alimentat separat |
| Frontend | o pagină React + Chart.js, pe jumătatea dreaptă a ecranului |

---

## 1. Scop și principii

Livrăm un demo care rulează cap-coadă: două simulări SUMO în paralel (semafor clasic vs AI) cu același trafic, un dashboard live, semaforul fizic ESP32 cu fail-safe și percepție video din camera reală din Piața Unirii.

**Principii de lucru**

- **Lanțul cap-coadă primul.** Totul se leagă întâi cu un controler simplu (max-pressure). AI-ul antrenat se pune la final, în locul lui.
- **Contractele de date (secțiunea 5) sunt fixe.** Modulele se pot rescrie, interfețele dintre ele nu. Orice schimbare de contract se face simultan în `schemas.py`, `types.ts` și în acest plan.
- **Fiecare modul are mod „mock”.** Frontend-ul merge fără SUMO, serverul merge fără ESP32, video-ul merge pe clip fără internet.
- **O singură sursă de configurare:** `config.yaml`. Nicio valoare hardcodată (port, praguri, căi).
- **TraCI se atinge doar din firul de simulare.** Nu e thread-safe; comenzile vin printr-o coadă.
- **Ora de „freeze”.** După ea nu mai intră funcții noi, doar reparații și repetiții.

**Gata pentru demo înseamnă:**

- [ ] Un singur script pornește totul în mai puțin de 30 s
- [ ] Graficul arată două linii live, cu același trafic în ambele simulări
- [ ] Rush Hour intră în ambele simulări, iar AI-ul golește coada mai repede
- [ ] Oprit serverul sau scos cablul de date: ESP32 trece pe avarie în cel mult 3 s, prin galben și roșu general
- [ ] La reconectare, placa revine la AI fără salt brusc între verzi
- [ ] Procentul din pitch provine din evaluarea pe mai multe seed-uri (secțiunea 8), nu dintr-o singură rulare
- [ ] Panoul video arată cozile detectate pe camera din Piața Unirii (live sau din clip)
- [ ] Există un video de rezervă cu demo-ul complet

---

## 2. Arhitectura generală

Un singur proces Python (`server/main.py`) ține simulările, controlerul, metricile, WebSocket-ul și portul serial. Frontend-ul și modulul video sunt procese separate care vorbesc doar prin contractele din secțiunea 5.

```text
 SUMO clasic (fix, headless) ◄──TraCI──┐
                                       ├──► SimEngine ──tick / comenzi──► FastAPI ◄──WS + REST──► Dashboard web
 SUMO AI (sumo-gui, vizibil)  ◄──TraCI──┘   (controler,                    ▲
                                             metrici)                       │ POST /api/vision
                                               │                            │ POST /api/spawn
                                               │ ultima stare               │
                                               ▼                     Video: webcam Piața Unirii
                                         SerialBridge                 (captură / clip) + YOLO
                                               │
                                          serial USB
                                               ▼
                                       ESP32 + LED-uri + LCD
                                       (fail-safe local)
```

SimEngine e singurul care vorbește cu SUMO; dashboard-ul, placa și video-ul vorbesc doar cu serverul.

**Fire de execuție în server**

| Fir | Ce face | Atinge |
| --- | --- | --- |
| SimEngine | avansează ambele simulări în lockstep, rulează controlerul, calculează metricile | TraCI (exclusiv) |
| SerialBridge | trimite starea la ESP32 la 500 ms și la fiecare schimbare de fază, citește ACK-urile, se reconectează | portul serial |
| asyncio (FastAPI) | REST, WebSocket, difuzarea tick-urilor | coada de comenzi, ultima stare |

**Fluxul unui tick:** comenzile din coadă (Rush Hour, reset, spawn) se aplică, controlerul alege fazele, simularea AI avansează `delta_time` secunde, simularea clasică e adusă la același moment, se calculează metricile, iar tick-ul pleacă spre dashboard și spre ESP32.

---

## 3. Stack tehnologic și versiuni

Python 3.11 pentru tot backend-ul. După prima instalare care merge, rulați `pip freeze > requirements.txt` și nu mai actualizați nimic până după hackathon.

| Zonă | Tehnologie | De reținut |
| --- | --- | --- |
| Simulare | SUMO (ultima versiune stabilă), TraCI, `libsumo` | `SUMO_HOME` setat; `libsumo` doar la antrenare |
| AI | `sumo-rl`, `gymnasium`, `pettingzoo`, `supersuit`, `stable-baselines3`, `torch` (CPU) | combinația de versiuni e fragilă: fixați-o devreme |
| Server | `fastapi`, `uvicorn`, `pydantic`, `pyyaml`, `pyserial` | un singur proces |
| Video | `ultralytics` (YOLO nano), `supervision`, `opencv-python`, `mss` (captură de ecran), `requests` | descărcați modelul `.pt` dinainte |
| Frontend | Vite + React + TypeScript, Tailwind CSS, `chart.js` + `react-chartjs-2` + `chartjs-plugin-annotation` | build-ul static e servit de FastAPI |
| Firmware | Arduino pe ESP32 (Arduino IDE sau PlatformIO), `LiquidCrystal_I2C` | responsabilitatea echipei de hardware |

Dacă `supersuit` refuză să meargă cu versiunea de PettingZoo: antrenați cu `SumoEnvironment(single_agent=True)` pe intersecția A și aplicați aceeași politică și pe B (merge doar dacă au aceeași structură de faze).

---

## 4. Structura proiectului și configurarea

```text
semafoare-ai/
├── CLAUDE.md                  # reguli pentru Claude (secțiunea 18)
├── PLAN.md                    # acest document
├── config.yaml                # configurarea unică
├── requirements.txt           # versiuni fixate
├── docs/
│   └── zone_piata_unirii.jpg  # zonele propuse pe cadrul camerei
├── sumo/
│   ├── map.osm                # extrasul OSM din jurul Pieței Unirii
│   ├── net.net.xml            # rețeaua curățată în netedit
│   ├── routes.rou.xml         # trafic variabil + rutele pentru Rush Hour
│   ├── demo.sumocfg
│   └── gui-settings.xml       # zoom, schemă de culori pentru proiector
├── ai/
│   ├── env_factory.py         # construiește mediul sumo-rl din config
│   ├── observation.py         # NeighborObservation
│   ├── reward.py              # traffic_reward
│   ├── train.py
│   ├── evaluate.py
│   └── models/                # ppo_traffic.zip + checkpoints/
├── controllers/
│   ├── base.py                # interfața Controller
│   ├── fixed.py
│   ├── max_pressure.py
│   ├── ppo.py
│   └── spillback_guard.py
├── server/
│   ├── main.py                # FastAPI: REST + WebSocket + pornire
│   ├── sim_engine.py          # cele două simulări în lockstep
│   ├── metrics.py
│   ├── serial_bridge.py
│   ├── schemas.py             # modelele pydantic ale contractelor
│   └── mock.py                # telemetrie falsă pentru frontend
├── vision/
│   ├── sources.py             # clip | captură de ecran | snapshot | flux
│   ├── calibrate_zones.py     # desenezi poligoanele pe un cadru
│   ├── detect.py              # crop + YOLO + tracking + cozi + linii de intrare
│   ├── demand_from_video.py   # numărători → debite în routes.rou.xml
│   ├── zones.json             # anexa A
│   └── clips/                 # clipul de rezervă (doar cu acordul sursei)
├── web/                       # Vite + React + TS
│   └── src/{components,hooks}/, types.ts
├── firmware/esp32_semafor/esp32_semafor.ino
├── scripts/
│   ├── build_net.ps1 | .sh
│   ├── run_demo.ps1 | .sh
│   └── fake_esp.py            # emulează răspunsurile ESP32 (opțional)
└── results/                   # eval.csv, grafice, loguri
```

```yaml
# config.yaml — valorile marcate „după M1” se completează după curățarea hărții
location:
  name: "Piața Unirii, Iași"
  lat: 47.1655
  lon: 27.5790
sumo:
  net: sumo/net.net.xml
  routes: sumo/routes.rou.xml
  seed: 42
  time_to_teleport: -1
sim:
  speed: 2                  # 2 = de două ori mai repede decât timpul real
  episode_s: 3600
tls:
  ids: [A, B]               # după M1
  main: A                   # intersecția oglindită pe ESP32 și văzută de cameră
  yellow_s: 3
  min_green_s: 10
  max_green_s: 60
rl:
  delta_time: 5
  model_path: ai/models/ppo_traffic.zip
controller: max_pressure    # ppo | max_pressure | fixed
spillback:
  enabled: true
  occupancy_threshold: 0.85
rush_hour:
  vehicles: 40              # se reglează după testul de gridlock din M1
  spread_s: 20
  routes: [blv_dir1, blv_dir2]
serial:
  port: COM5                # sau /dev/ttyUSB0
  baud: 115200
  send_interval_ms: 500
  ack_timeout_ms: 2000
server:
  host: 127.0.0.1
  port: 8000
  history_points: 300
vision:
  enabled: true
  mode: panel               # panel | twin
  source: file              # file | screen | snapshot | stream
  file: vision/clips/piata_unirii_1700.mp4
  screen_region: {left: 0, top: 0, width: 1280, height: 720}   # zona playerului pe ecran
  snapshot_url: ""          # doar cu acordul sursei
  stream_url: ""            # doar dacă îl primiți de la WebcamRomania
  fps: 10
  zones: vision/zones.json
  model: yolo11n.pt         # sau yolov8n.pt
  imgsz: 640
  conf: 0.35
```

---

## 5. Contracte de date

Acestea sunt singurele interfețe dintre module. Se scriu o dată în `server/schemas.py` (pydantic) și în `web/src/types.ts`, înainte de orice altă logică.

### 5.1 WebSocket `/ws` — tick (server → dashboard, la fiecare secundă simulată, 2/s real la `sim.speed: 2`)

```json
{
  "type": "tick",
  "sim_time": 523,
  "controller": "ppo",
  "rush_active": false,
  "fix": {"avg_wait_s": 41.2, "queue_veh": 37, "throughput_vph": 820, "trip_wait_s": 38.0},
  "ai":  {"avg_wait_s": 21.7, "queue_veh": 18, "throughput_vph": 905, "trip_wait_s": 19.6},
  "improvement_pct": -48.4,
  "intersections": [
    {"id": "A", "green_phase": 1, "phase_label": "Bulevard", "state": "green",
     "time_in_phase_s": 12, "queues": {"N": 5, "S": 3, "E": 12, "V": 1}, "hold": false}
  ],
  "esp": {"online": true, "last_ack_ms": 340, "mode": "AI"},
  "vision": {"online": true, "source": "file", "queues": {"blv_dir1": 7, "lateral": 3}, "avg_stop_s": 24.0}
}
```

- `state`: `green` | `yellow` | `all_red`. `esp.mode`: `AI` | `AVARIE` | `NECONECTAT`.
- `improvement_pct` e `null` în primele 120 s sau sub 30 de vehicule ieșite din fiecare simulare.
- La conectare, serverul trimite întâi `{"type":"history","ticks":[…]}` cu ultimele 300 de tick-uri, ca un refresh al paginii să nu golească graficul.

### 5.2 WebSocket — eveniment

```json
{"type": "event", "sim_time": 530, "kind": "rush_hour", "level": "info", "msg": "Rush Hour: +40 vehicule pe bulevard"}
```

`kind`: `rush_hour`, `rush_end`, `spillback_hold`, `esp_online`, `esp_offline`, `heartbeat_paused`, `heartbeat_resumed`, `controller_changed`, `reset`, `vision_online`, `vision_offline`.

### 5.3 REST

| Metodă | Cale | Corp | Efect |
| --- | --- | --- | --- |
| POST | `/api/rush` | `{"vehicles": 40}` | injectează aceleași vehicule în ambele simulări |
| POST | `/api/reset` | — | repornește ambele simulări, golește istoricul |
| POST | `/api/controller` | `{"name": "max_pressure"}` | schimbă controlerul AI din mers |
| POST | `/api/heartbeat` | `{"enabled": false}` | oprește trimiterea spre ESP32 (simulează căderea serverului) |
| GET | `/api/state` | — | ultimul tick + configurarea publică |
| POST | `/api/vision` | vezi 5.6 | cifrele de la modulul video |
| POST | `/api/spawn` | `{"approach": "blv_dir1"}` | mod geamăn: o mașină reală intră în ambele simulări |
| WS | `/ws` | — | tick-uri + evenimente |

### 5.4 Serial, laptop → ESP32

115200 baud, o linie ASCII terminată cu `\n`, maximum 64 de caractere.

```text
P:1,Y:1500,Q:12,W:34,M:AI,HB:1532
```

| Câmp | Sens |
| --- | --- |
| `P` | faza verde dorită la intersecția principală (index 0…n-1) |
| `Y` | durata galbenului în modul AI, în ms (`yellow_s × 1000 / sim.speed`, ca LED-urile să țină pasul cu simularea) |
| `Q` | vehicule la coadă la intersecția principală, pentru LCD |
| `W` | așteptarea medie în secunde, pentru LCD |
| `M` | `AI` sau `FIX` (controlerul activ) |
| `HB` | contor care crește la fiecare mesaj; un contor blocat = server înghețat |

Trimis la fiecare schimbare de fază și oricum la 500 ms.

### 5.5 Serial, ESP32 → laptop

```text
ACK:1532,L:1,S:AI
```

`ACK` = ultimul HB primit, `L` = faza aprinsă efectiv, `S` = `AI` | `AVARIE`. Serverul consideră placa online dacă a primit un ACK în ultimele 2000 ms.

### 5.6 Video → server, `POST /api/vision` la fiecare secundă

```json
{
  "ts": 1739,
  "source": "screen",
  "queues": {"blv_dir1": 7, "lateral": 3},
  "arrivals_per_min": {"blv_dir1": 14, "blv_dir2": 11, "lateral": 6},
  "avg_stop_s": 24.0
}
```

Cheile corespund zonelor din `zones.json` (anexa A).

### 5.7 WebSocket — frame (server → dashboard, la fiecare secundă simulată)

Pozițiile pentru harta 3D, din ambele simulări. Nu intră în istoric.

```json
{
  "type": "frame",
  "sim_time": 523,
  "fix": {"veh": [[17, 102.4, -40.1, 112.0, 0, 8.3]], "ped": [[905, 12.0, 4.5, 90.0]], "tls": {"A": "GGgrrrgGGrGr"}},
  "ai":  {"veh": [[17, 101.9, -39.8, 112.0, 0, 8.1]], "ped": [], "tls": {"A": "rrrgggrrrGrG"}}
}
```

`veh` = `[id, x, y, unghi°, tip (0 mașină, 1 autobuz), viteză m/s]`, `ped` = `[id, x, y, unghi°]`, coordonate SUMO în metri. Același vehicul are același `id` în ambele simulări.

### 5.9 REST `GET /api/results`

`{"rows": [...]}` cu rândurile din `results/eval_summary.csv` (evaluarea pe seed-uri din `ai/evaluate.py`), pentru pagina „Rezultate”.

### 5.8 REST `GET /api/network`

Geometria statică pentru harta 3D: benzi (`road`, `sidewalk`, `crossing`, `walkingarea`) cu formă și lățime, poligoanele intersecțiilor, iar pentru fiecare semafor: capetele de semafor pe benzile de intrare (cu indicii legăturilor din șirul de stare), trecerile de pietoni, brațele (`N`/`S`/`E`/`V`, numele străzii) și ce brațe deschide fiecare fază verde; plus clădirile din OSM (contur și înălțime), pentru context. Tipurile exacte sunt în `web/src/types.ts` (`Network`).

---

## 6. Modulul 1 — Harta Piața Unirii și scenariul de trafic

Rezultat: o rețea SUMO curată cu intersecția din cadrul camerei (A) și următoarea intersecție semaforizată pe bulevard (B), plus un fișier de rute cu trafic normal, vârf și iar normal. Durată estimată: 1,5–2 h.

**Ce se vede în cameră și trebuie să existe în hartă**

- Bulevardul lat cu linie de tramvai pe mijloc, care pleacă din prim-plan spre fundal.
- Trecerea de pietoni (cu linia de stop) la mijlocul cadrului, lângă clădirea cu cupolă.
- Strada laterală care intră din dreapta, între clădirea cu cupolă și hotelul din dreapta.
- Parcările (stânga jos și dreapta, cu stație de taxi) — **nu** se modelează ca trafic.

Pagina camerei descrie locul ca punctul unde se întâlnesc Bd. Ștefan cel Mare, str. Alexandru Lăpușneanu și str. Cuza Vodă. Identificați pe OpenStreetMap care dintre ele este bulevardul din cadru și care e strada laterală, apoi notați asta aici.

**Pași**

1. **Exportați zona.** Din osmWebWizard (centrat pe 47.1655, 27.5790) sau din openstreetmap.org/export, un dreptunghi care conține Piața Unirii și intersecția următoare pe bulevard. Salvați ca `sumo/map.osm`.
2. **Generați rețeaua** cu `netconvert` (comanda în `scripts/build_net`, ca să poată fi rulată din nou):

   ```text
   netconvert --osm-files sumo/map.osm -o sumo/net.net.xml --tls.guess-signals --tls.join --junctions.join --remove-edges.isolated --keep-edges.by-vclass passenger
   ```

   Tramvaiul se lasă deoparte la început (vezi pasul 7).
3. **Curățați în `netedit`.** Un singur semafor per intersecție; redenumiți-le `A` (cea din cameră) și `B`; verificați programul (fazele verzi + galben 3 s); ștergeți străduțele laterale care nu contribuie.
4. **Scrieți rutele** cu id fix: `blv_dir1` (direcția care se îndepărtează de cameră — cea cu coada vizibilă, zona verde), `blv_dir2` (direcția spre cameră), `lat_in` (strada laterală), plus virajele principale.

   ```xml
   <routes>
     <vType id="car" accel="2.6" decel="4.5" length="4.5" minGap="2.5" maxSpeed="13.9" sigma="0.5"/>
     <route id="blv_dir1" edges="…"/>
     <route id="blv_dir2" edges="…"/>
     <route id="lat_in"   edges="…"/>
     <!-- normal / vârf / normal pe bulevard -->
     <flow id="f_d1_1" route="blv_dir1" type="car" begin="0"    end="1200" vehsPerHour="800"  departLane="best" departSpeed="max"/>
     <flow id="f_d1_2" route="blv_dir1" type="car" begin="1200" end="2400" vehsPerHour="1500" departLane="best" departSpeed="max"/>
     <flow id="f_d1_3" route="blv_dir1" type="car" begin="2400" end="3600" vehsPerHour="800"  departLane="best" departSpeed="max"/>
     <!-- la fel pentru blv_dir2; strada laterală cu 150–250 veh/h -->
   </routes>
   ```

   Valorile sunt de pornire. Le înlocuiți cu debitele măsurate din cameră (`demand_from_video.py`, Modulul 7).
5. **Configurați demo-ul.** `demo.sumocfg` cu `--time-to-teleport -1`, seed fix; `gui-settings.xml` cu zoom pe A și B, orientat ca în cameră (bulevardul vertical, strada laterală din dreapta), ca juriul să recunoască locul.
6. **Testați limitele.** Rulați 3600 s fără interfață și verificați că nu apare gridlock. Apoi injectați vehicule pe bulevard și notați câte suportă rețeaua: valoarea devine `rush_hour.vehicles`.
7. **Tramvaiul (opțional, după ce restul merge).** Regenerați cu `--keep-edges.by-vclass passenger,tram`, adăugați un `vType` cu `vClass="tram"` și un `flow` la 6–10 minute. Pregătește terenul pentru prioritatea tramvaiului (secțiunea 17).

**Livrabile:** `net.net.xml`, `routes.rou.xml`, `demo.sumocfg`, `gui-settings.xml`, id-urile semafoarelor în `config.yaml`.

**Anunțați echipa de hardware:** câte faze verzi are intersecția A și ce direcții deschide fiecare. De aici rezultă câte grupuri de LED-uri se montează.

**Gata când:** `sumo-gui -c sumo/demo.sumocfg` arată traficul fluid pe programul fix, fără teleportări și fără blocaj total la vârf, iar zona arată recognoscibil ca Piața Unirii.

---

## 7. Modulul 2 — Mediul RL și antrenarea AI

Rezultat: `ai/models/ppo_traffic.zip`, o politică PPO comună pentru A și B, antrenată 100k–300k pași pe trafic variabil. Durată: 2–3 h, din care mare parte rulează nesupravegheat.

**Designul agentului**

| Element | Alegere |
| --- | --- |
| Mediu | `sumo_rl.parallel_env` (PettingZoo), un agent per semafor |
| Acțiune | indexul următoarei faze verzi, ales la fiecare `delta_time = 5` s |
| Observație | cea implicită din `sumo-rl` (faza curentă, flag de verde minim, densitate și coadă pe benzile de intrare) + ocuparea benzilor de ieșire, ca semnal că vecinul se umple |
| Recompensă | funcția de mai jos |
| Constrângeri | galben 3 s, verde minim 10 s, verde maxim 60 s |
| Algoritm | PPO cu `MlpPolicy`, politică partajată între agenți prin `supersuit` |
| Episod | 3600 s simulate, seed aleator la antrenare, seed fix la evaluare |

**Recompensa** (coeficienți de pornire, se ajustează dacă agentul se comportă ciudat)

```text
r_t = (W_{t-1} − W_t) / 100 − 0.05 · Q_t − 0.5 · N>90s_t − 0.5 · S_t
```

W = așteptarea cumulată pe benzile de intrare, Q = vehicule la coadă, N>90s = vehicule care așteaptă de peste 90 s, S = benzi de ieșire ocupate peste 85%. Primul termen recompensează scăderea așteptării; ceilalți pedepsesc cozile, așteptările lungi și trimiterea mașinilor într-o intersecție plină.

**`ai/observation.py`** (schelet; Claude verifică atributele în codul `sumo-rl` instalat)

```python
import numpy as np
from gymnasium import spaces
from sumo_rl.environment.observations import ObservationFunction

class NeighborObservation(ObservationFunction):
    """Observația implicită sumo-rl + ocuparea benzilor de ieșire (spre vecin)."""

    def __call__(self):
        ts = self.ts
        phase = [1 if ts.green_phase == i else 0 for i in range(ts.num_green_phases)]
        min_green = [0 if ts.time_since_last_phase_change < ts.min_green + ts.yellow_time else 1]
        density = ts.get_lanes_density()
        queue = ts.get_lanes_queue()
        out_occ = [min(1.0, ts.sumo.lane.getLastStepOccupancy(l) / 100) for l in ts.out_lanes]
        return np.array(phase + min_green + density + queue + out_occ, dtype=np.float32)

    def observation_space(self):
        n = self.ts.num_green_phases + 1 + 2 * len(self.ts.lanes) + len(self.ts.out_lanes)
        return spaces.Box(low=0, high=1, shape=(n,), dtype=np.float32)
```

**`ai/reward.py`**

```python
def traffic_reward(ts):
    wait = sum(ts.get_accumulated_waiting_time_per_lane()) / 100.0
    prev = getattr(ts, "_prev_wait", wait)
    ts._prev_wait = wait
    queue = ts.get_total_queued()
    long_wait = sum(
        1
        for lane in ts.lanes
        for v in ts.sumo.lane.getLastStepVehicleIDs(lane)
        if ts.sumo.vehicle.getAccumulatedWaitingTime(v) > 90
    )
    saturated = sum(1 for l in ts.out_lanes if ts.sumo.lane.getLastStepOccupancy(l) > 85)
    return (prev - wait) - 0.05 * queue - 0.5 * long_wait - 0.5 * saturated
```

**`ai/train.py`**

```python
"""python -m ai.train --config config.yaml --steps 200000
Pentru viteză: setați LIBSUMO_AS_TRACI=1 înainte de rulare (doar la antrenare)."""
import argparse, yaml
import sumo_rl
import supersuit as ss
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import VecMonitor
from stable_baselines3.common.callbacks import CheckpointCallback
from ai.observation import NeighborObservation
from ai.reward import traffic_reward

def make_env(cfg, num_envs=4):
    env = sumo_rl.parallel_env(
        net_file=cfg["sumo"]["net"],
        route_file=cfg["sumo"]["routes"],
        use_gui=False,
        num_seconds=cfg["sim"]["episode_s"],
        delta_time=cfg["rl"]["delta_time"],
        yellow_time=cfg["tls"]["yellow_s"],
        min_green=cfg["tls"]["min_green_s"],
        max_green=cfg["tls"]["max_green_s"],
        reward_fn=traffic_reward,
        observation_class=NeighborObservation,
        sumo_seed="random",
        additional_sumo_cmd="--time-to-teleport -1",
    )
    env = ss.pad_observations_v0(env)
    env = ss.pad_action_space_v0(env)
    env = ss.pettingzoo_env_to_vec_env_v1(env)
    env = ss.concat_vec_envs_v1(env, num_envs, num_cpus=num_envs, base_class="stable_baselines3")
    return VecMonitor(env)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--steps", type=int, default=200_000)
    p.add_argument("--resume", default=None)
    a = p.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    env = make_env(cfg)
    if a.resume:
        model = PPO.load(a.resume, env=env)
    else:
        model = PPO(
            "MlpPolicy", env,
            learning_rate=3e-4, n_steps=512, batch_size=256, n_epochs=10,
            gamma=0.99, gae_lambda=0.95, clip_range=0.2, ent_coef=0.01,
            tensorboard_log="results/tb", verbose=1,
        )
    ckpt = CheckpointCallback(save_freq=10_000, save_path="ai/models/checkpoints", name_prefix="ppo")
    model.learn(total_timesteps=a.steps, callback=ckpt)
    model.save(cfg["rl"]["model_path"])

if __name__ == "__main__":
    main()
```

**Pași**

1. `env_factory.py` + un test de fum: un episod cu acțiuni aleatoare, se afișează recompensa totală și dimensiunea observației per agent.
2. `observation.py` și `reward.py`; testul de fum trebuie să meargă din nou.
3. Antrenare scurtă de 5 000 de pași, doar ca să confirmați că totul rulează și se salvează.
4. Antrenarea completă, urmărită în TensorBoard (`tensorboard --logdir results/tb`): `ep_rew_mean` trebuie să crească.
5. Evaluare cu Modulul 3. Dacă PPO nu bate max-pressure: mai mulți pași, recompensă simplificată (doar primul termen) sau demo cu max-pressure.

**Capcane**

- La antrenare, `supersuit` completează observațiile cu zerouri până la dimensiunea celei mai mari. În demo trebuie completate identic, altfel modelul primește altceva decât a învățat.
- Un agent care schimbă faza la fiecare decizie înseamnă că verdele minim lipsește sau că recompensa favorizează schimbările. Verificați întâi `min_green`.
- Recompensa care stagnează de la început indică de obicei valori prea mari. Normalizați termenii.

---

## 8. Modulul 3 — Controlere și evaluare

Toate controlerele au aceeași interfață, deci serverul le schimbă fără să știe ce e în spate. Evaluarea decide care intră în demo și produce cifra din pitch. Durată: 2 h.

**Interfața (`controllers/base.py`)**

```python
from typing import Protocol
import numpy as np

class Controller(Protocol):
    name: str
    def reset(self, env) -> None: ...
    def act(self, observations: dict[str, np.ndarray], env) -> dict[str, int]:
        """Primește observațiile per semafor, întoarce faza verde dorită per semafor."""
```

| Controler | Logica | Rol |
| --- | --- | --- |
| `fixed` | ciclează fazele verzi cu durate fixe din config | verificare, comparație |
| `max_pressure` | pentru fiecare fază verde: suma (coadă pe intrare − coadă pe ieșire) pe legăturile pe care le deschide; alege maximul | controler de pornire și plan B |
| `ppo` | `model.predict(obs, deterministic=True)` pe observația completată cu zerouri ca la antrenare | AI-ul principal |
| `spillback_guard` | înveliș peste oricare: dacă faza aleasă trimite mașini spre o bandă ocupată peste 85%, păstrează faza curentă și emite `spillback_hold` | coordonarea vizibilă A↔B |

Max-pressure folosește `trafficlight.getControlledLinks` și șirul de stare al fiecărei faze verzi, ca să afle ce legături deschide.

**Evaluarea (`ai/evaluate.py`)**

- Rulează fiecare variantă pe 5 seed-uri fixe × 3600 s, fără interfață: programul fix al hărții, programul `actuated` (rețea generată cu `netconvert --tls.default-type actuated`), `max_pressure`, `ppo`, `ppo + spillback_guard`.
- Rulează și scenariul Rush Hour (aceleași vehicule injectate la secunda 900).
- Măsoară din `tripinfo`: așteptarea medie per vehicul, durata medie a călătoriei, vehicule ieșite pe oră, coada maximă.
- Salvează `results/eval.csv` și `results/eval.png`.
- Rulează pe rutele calibrate din cameră, când există (Modulul 7).

**Gata când:** există un tabel cu media și abaterea pe seed-uri pentru fiecare variantă. Controlerul din demo e cel mai bun dintre ele, iar procentul din pitch e media față de programul fix (și, separat, față de `actuated`).

---

## 9. Modulul 4 — Motorul de simulare cu geamăn

`SimEngine` rulează simularea AI (cu `sumo-gui`) și simularea clasică (fără interfață) pe aceeași rețea, cu aceleași rute și același seed, avansându-le împreună dintr-un singur fir. Durată: 2–2,5 h.

**Alegeri de implementare**

- **Simularea AI** folosește `sumo_rl.SumoEnvironment` (varianta cu dicționare, fără PettingZoo), cu exact parametrii de la antrenare, plus `use_gui=True`. Așa observația e calculată de același cod ca la antrenare.
- **Simularea clasică** e o conexiune TraCI separată (`traci.start(cmd, label="fix")`), cu programul fix din rețea.
- **Viteza vizuală:** `sumo-gui --delay` = `1000 / sim.speed` ms pe pas. Simularea clasică nu are întârziere; e doar adusă la același moment.

**Bucla principală (`server/sim_engine.py`)**

```python
class SimEngine(threading.Thread):
    def run(self):
        self.ai_env = make_demo_env(self.cfg, use_gui=True)       # SumoEnvironment
        obs = self.ai_env.reset()
        self.fix = start_fix_sim(self.cfg)                         # traci, label="fix"
        while not self.stopping:
            self.apply_commands()                  # rush, reset, controller, spawn — din queue.Queue
            actions = self.controller.act(obs, self.ai_env)
            actions = self.guard.filter(actions, self.ai_env)     # spillback_guard
            obs, _, _, _ = self.ai_env.step(actions)              # avansează delta_time secunde
            t = self.ai_env.sim_step
            self.fix.simulationStep(t)                            # simularea clasică ajunge la t
            tick = self.metrics.compute(self.ai_env.sumo, self.fix, t)
            self.publish(tick)                     # spre WebSocket și SerialBridge
```

**Metrici (`server/metrics.py`)**, calculate identic pentru ambele simulări:

| Câmp | Definiție |
| --- | --- |
| `avg_wait_s` | media așteptării acumulate a vehiculelor aflate acum în rețea, netezită pe 30 s (linia de pe grafic) |
| `queue_veh` | vehicule sub 0,1 m/s pe benzile de intrare ale lui A și B |
| `trip_wait_s` | media așteptării finale a vehiculelor ieșite din rețea; ultima valoare cunoscută se reține per vehicul și se adaugă la ieșire (`getArrivedIDList`) |
| `throughput_vph` | vehicule ieșite în ultimele 300 s × 12 |
| `improvement_pct` | `(ai.trip_wait_s − fix.trip_wait_s) / fix.trip_wait_s × 100`, negativ = mai bine |

**Rush Hour.** `vehicles` mașini împărțite pe `spread_s` secunde, pe rutele din config, cu id-uri `rush_<k>`. Se adaugă în ambele simulări în același tick (`vehicle.add(id, route, typeID="car", depart="now", departLane="best")`). Se emit evenimentele `rush_hour` și, după ultima mașină, `rush_end`.

**Spawn din video (mod geamăn).** La `POST /api/spawn` se adaugă o mașină pe ruta corespunzătoare zonei (`blv_dir1`, `blv_dir2`, `lat_in`) în ambele simulări, cu id `real_<k>`.

**Reset.** Închide ambele simulări, le repornește, golește istoricul metricilor și emite `reset`.

**Comunicarea între fire.** Comenzile intră printr-un `queue.Queue` citit doar de `SimEngine`. Tick-urile ajung în bucla asyncio prin `loop.call_soon_threadsafe`, iar ultima stare e ținută sub un `Lock` pentru `SerialBridge`.

**Gata când:** serverul rulează 10 minute fără să se desincronizeze, iar Rush Hour se vede pe ambele linii ale graficului.

---

## 10. Modulul 5 — Serverul FastAPI și puntea serială

Serverul pornește motorul de simulare (sau varianta mock), puntea serială și WebSocket-ul. Tot el servește dashboard-ul compilat, deci în demo e o singură adresă. Durată: 2 h.

**`server/main.py`**

- Pornire: `python -m server.main --config config.yaml [--mock] [--no-serial] [--controller max_pressure]`.
- În `lifespan`: pornește `SimEngine` sau `MockEngine`, `SerialBridge` (dacă nu e `--no-serial`) și sarcina de difuzare.
- Endpoint-urile exact ca în secțiunea 5; corpurile validate cu modelele din `schemas.py`.
- `ConnectionManager` pentru WebSocket: la conectare trimite `history`, apoi fiecare tick și eveniment. Un client care cade e scos din listă fără să blocheze ceilalți.
- Ultimele date de la `/api/vision` intră în câmpul `vision` al tick-ului; dacă nu vin 5 s, `vision.online = false` și se emite `vision_offline`.
- Servește `web/dist` la `/`; CORS permis pentru `localhost:5173` (serverul de dezvoltare Vite).

**`server/mock.py`** generează tick-uri plauzibile fără SUMO: linia clasică urcă lent, linia AI stă cu 40–50% mai jos, Rush Hour produce un vârf pe ambele, iar fazele se schimbă la 10–40 s. Frontend-ul se dezvoltă integral pe mock.

**`server/serial_bridge.py`**

1. **Deschidere fără reset:** `s = serial.Serial(); s.port = …; s.baudrate = 115200; s.dtr = False; s.rts = False; s.open()`. Altfel ESP32 repornește la fiecare conectare.
2. **Scriere:** imediat la schimbarea fazei dorite și oricum la `send_interval_ms`. `HB` crește la fiecare mesaj.
3. **Citire:** liniile `ACK:` actualizează `last_ack`; online = ACK primit în ultimele `ack_timeout_ms`. Liniile malformate sunt ignorate și scrise în `results/serial.log`.
4. **Reconectare:** la `SerialException` închide portul și reîncearcă la 2 s. Tranzițiile emit `esp_offline` / `esp_online`.
5. **Simularea căderii:** când `/api/heartbeat` primește `enabled: false`, puntea nu mai trimite nimic (portul rămâne deschis), ca placa să intre singură pe avarie.
6. **Port automat (opțional):** dacă portul din config lipsește, caută în `serial.tools.list_ports` un adaptor CP210x sau CH340.

**`scripts/fake_esp.py`** (opțional): pentru testare fără placă, răspunde cu ACK-uri pe un port virtual sau direct dintr-un mod de test al punții.

**Gata când:** cu placa conectată, dashboard-ul arată „ESP32 ONLINE”; cu cablul de date scos, trece pe OFFLINE în cel mult 2 s, iar la reconectare revine singur.

---

## 11. Modulul 6 — Frontend-ul (dashboard)

O singură pagină, gândită pentru jumătatea dreaptă a unui ecran de 1920×1080 (cca 960×1080) și lizibilă pe proiector de la 5 metri. Se dezvoltă pe serverul mock și nu depinde de SUMO. Durată: 3 h.

```text
┌──────────────────────────────────────────────────────────┐
│ Semafoare AI — Piața Unirii, Iași   [PPO] [ESP32 ONLINE] │  1 status
├──────────────────┬──────────────────┬────────────────────┤
│      −48%        │   38 s → 20 s    │     37 vs 18       │  2 cifre mari
│ timp de așteptare│ așteptare medie  │ vehicule la coadă  │
├──────────────────┴──────────────────┴────────────────────┤
│  ── Semafor clasic (roșu)   ── AI (verde)                │
│                        ░░Rush Hour░░                     │  3 grafic
│  ~~~~~~~~~~~~~~~~~~~~~~░░░/\░░░░░~~~~~~~~~~~~~~          │
│  ______________________░░/\_░░░░______________           │
├────────────────────────────┬─────────────────────────────┤
│ Intersecția A              │ Intersecția B               │  4 intersecții
│  schemă + cozi pe brațe    │  [REȚINE FLUXUL]            │
├────────────────────────────┼─────────────────────────────┤
│ Camera Piața Unirii        │ Jurnal evenimente           │  5 video, jurnal,
│ (cadru cu detecții)        │ [Rush Hour] [Cădere] [Reset]│    control
└────────────────────────────┴─────────────────────────────┘
```

Ochiul juriului merge întâi la procentul verde, apoi la grafic; restul paginii confirmă că totul e live.

**Zonele paginii, de sus în jos**

1. **Bara de status (56 px).** Titlul „Semafoare AI — Piața Unirii, Iași” și pilule: SIMULARE (verde / gri), CONTROLER: PPO, ESP32 ONLINE / OFFLINE (roșu pulsant când e offline), TEREN: AI / AVARIE, CAMERĂ: LIVE / CLIP / OFF, ora simulării.
2. **Trei cifre mari.** Scăderea așteptării (ex. „−48%”, verde, cea mai mare de pe pagină); așteptarea medie „38 s → 20 s” (roșu → verde); coada acum „37 vs 18 vehicule”. Până când `improvement_pct` e disponibil, primul card arată „se calculează…”.
3. **Graficul (cca 40% din înălțime).** Două linii: roșu „Semafor clasic”, verde „AI”; ultimele 300 s simulate; axa Y în secunde. În timpul Rush Hour apare o bandă portocalie semitransparentă cu eticheta „Rush Hour”. Animațiile dezactivate; actualizare cu `chart.update('none')`.
4. **Cardurile intersecțiilor A și B.** O schemă SVG cu brațele intersecției: pe fiecare braț, culoarea semaforului și o bară de coadă cu număr. Dedesubt, faza și timpul în fază. Când `hold` e activ, apare insigna „REȚINE FLUXUL — B saturat”.
5. **Panoul camerei.** Imaginea MJPEG de la modulul video (`:8001/stream`), cu zonele colorate și cozile detectate; eticheta „LIVE” sau „CLIP ÎNREGISTRAT” după sursă și „Sursa: WebcamRomania.ro”. Ascuns când `vision.online` e fals.
6. **Jurnalul de evenimente și controalele.** Ultimele 6 evenimente cu ora simulării. Butoane mari: „Rush Hour” (portocaliu), „Simulează căderea serverului” (comutator roșu), „Reset” (discret). Selectorul de controler stă ascuns sub „Avansat”.

**Stări speciale**

- WebSocket deconectat: un strat semitransparent „Reconectare…”, cu reîncercare la 1, 2, apoi 4 s.
- ESP32 offline: pilula devine roșie și apare bannerul „Semaforul de pe teren a trecut pe programul de avarie”.
- Scurtături de tastatură pentru pitch: `R` = Rush Hour, `F` = căderea serverului, `X` = reset.

**Stil vizual**

| Element | Valoare |
| --- | --- |
| Temă | deschisă, inspirată din forex_app (Aurex): carduri din sticlă mată (`.glass`, `rounded-3xl`), fundal cu degrade albastru |
| Fundal / carduri | `oklch(0.975 0.002 247)` + degrade albastru / alb 58% cu blur |
| Text / text secundar | `oklch(0.17 0.006 255)` / `oklch(0.53 0.008 255)` |
| Clasic / AI / Rush / accent | `#d93a30` / `#1f9d55` / `#ff9500` / `#0a84ff` |
| Font | fontul de sistem (SF Pro / Segoe UI), cifre `tabular-nums` |
| Dimensiuni | cifra principală 72 px, celelalte 48 px, text minim 16 px |

Toate etichetele sunt în română.

**Actualizare 18.10: patru pagini și hartă 3D** (taste `1`–`4`, `D` = detecție)

| Pagină | Conținut |
| --- | --- |
| Hartă live | Clasic și AI unul lângă altul, în 3D (three.js), camere sincronizate; vedere de ansamblu, „Vedere cameră” (Grand Hotel Traian) și fiecare intersecție |
| Panou | cifrele mari, graficul, harta AI cu etichetele intersecțiilor, camera, semaforul ESP32 oglindit, jurnalul |
| Intersecții | toate cele 5 intersecții deodată, fiecare cu camera ei 3D; moduri AI / Clasic / Comparație |
| Rezultate | impact cumulat (vehicul-ore, combustibil, CO₂), evaluarea pe 5 seed-uri, cronologia fazelor, metodologia |

Harta 3D folosește `GET /api/network` (§5.8) și mesajele `frame` (§5.7): mașini, autobuze și pietoni ca modele low-poly instanțiate, interpolate la 60 fps între cadrele de 2/s; modul „Detecție” desenează chenare 3D în stil lidar. Un singur canvas WebGL pentru toate vederile (`web/src/three/Stage.tsx`).

**Structura codului (`web/src`)**

- `types.ts`: copia exactă a contractelor din secțiunea 5.
- `hooks/useTelemetry.ts`: WebSocket cu reconectare, tampon de 300 de tick-uri, ultimele 6 evenimente, starea conexiunii.
- `api.ts`: `rush()`, `reset()`, `setController()`, `setHeartbeat()`.
- `components/`: `StatusBar`, `KpiCards`, `WaitChart`, `IntersectionCard`, `CameraPanel`, `EventLog`, `ControlPanel`.
- Fără router și fără bibliotecă de stare; `useReducer` e suficient.

**Gata când:** pe mock, pagina rulează 10 minute fără să încetinească, se citește la 1280×720 și toate butoanele declanșează evenimentul corespunzător.

---

## 12. Modulul 7 — Percepția video din webcam-ul Piața Unirii

Modulul transformă imaginea camerei WebcamRomania din Piața Unirii (montată pe Grand Hotel Traian) în cifre: câte mașini stau la coadă, cât așteaptă și câte sosesc pe minut. Nu blochează restul; se face după ce lanțul de bază merge. Durată: 3–4 h.

Pagina camerei: https://webcamromania.ro/webcam-orase/webcam-iasi/

![Zonele propuse pe cadrul camerei](docs/zone_piata_unirii.jpg)

*Zonele de mai sus sunt desenate de mână pe o captură de 2144×1240 și sunt aproximative; se ajustează în `calibrate_zones.py` pe un cadru la rezoluția reală.*

### 12.1 Ce oferă camera

| Aspect | Evaluare |
| --- | --- |
| Înălțime și unghi | sus, aproape de-a lungul bulevardului: mașinile din coadă nu se acoperă una pe alta |
| Mărimea mașinilor | 60–150 px în jumătatea de jos a cadrului; mici spre fundal |
| Coada vizibilă | direcția care se îndepărtează de cameră (zona verde), oprită la trecerea de pietoni din mijlocul cadrului |
| Direcția spre cameră | așteaptă dincolo de trecere, unde e mică: pentru ea se numără sosirile, nu coada |
| Strada laterală din dreapta | vizibilă, mașini medii: coadă aproximativă + sosiri |
| Probleme | parcări mari în stânga jos și în dreapta (cu stație de taxi), tramvai pe mijloc, distorsiune fisheye, pietoni mulți |

### 12.2 Acordul sursei (de făcut azi)

Site-ul indică „toate drepturile rezervate” și precizează că nu înregistrează imagini. Fluxul nu se extrage pe ascuns din player. Trimiteți emailul din **anexa B**. Până la răspuns se lucrează doar pe capturi de ecran pentru calibrare, fără să fie folosite public.

### 12.3 Surse de imagine (`vision/sources.py`)

Toate sursele întorc același lucru: cadre BGR la `vision.fps`.

| `source` | Cum | Folosire |
| --- | --- | --- |
| `file` | `cv2.VideoCapture(path)` pe clipul înregistrat, în buclă | **implicit pe scenă**, nu depinde de internet |
| `screen` | `mss` captează zona playerului deschis în browser, la ~10 cadre/s | demo live, cu acordul sursei |
| `snapshot` | descarcă periodic imaginea statică a camerei | doar cozi aproximative, fără tracking; doar cu acordul sursei |
| `stream` | `cv2.VideoCapture(url)` pe un link direct primit de la WebcamRomania | cea mai curată variantă, dacă vi-l dau |

### 12.4 Pași

1. **Înregistrarea de referință (cu acordul sursei):** 10–15 minute într-o zi lucrătoare, între 17:00 și 18:00 (vârf de trafic, încă lumină: apusul e acum pe la 18:15 și coboară). Salvați în `vision/clips/`. Fără acord, filmați voi o intersecție din punct înalt (planul B).
2. **`calibrate_zones.py`:** deschide un cadru, desenați cu mouse-ul crop-ul, poligoanele și liniile. Salvează coordonate **normalizate (0–1)**, ca să nu depindă de rezoluție. Punctul de plecare e anexa A.
3. **Crop înainte de detecție.** Din cadru se decupează doar dreptunghiul `crop`, apoi YOLO rulează pe decupaj la `imgsz=640`. Mașinile devin de câteva ori mai mari pentru model, iar detecția se îmbunătățește mult.
4. **`detect.py`:** YOLO nano (`conf=0.35`, clasele COCO car, motorcycle, bus, truck) + tracking ByteTrack. Persoanele și clasa „train” se ignoră.
5. **Zone:** o detecție contează doar dacă punctul de jos-centru al chenarului cade într-un poligon de bandă. Zonele `exclude` (parcările) se verifică primele. `PolygonZone` din `supervision` dă cozile, `LineZone` dă sosirile.
6. **Mașină oprită:** deplasarea în ultimele 2 s e sub 15% din înălțimea chenarului. Pragul relativ compensează perspectiva și fisheye-ul. Timpul de așteptare = cât a stat în starea asta.
7. **Tramvaiul:** chenarele foarte lungi (peste ~3 lungimi de mașină) sau clasa „train” se ignoră, ca un tramvai oprit să nu fie numărat ca 5 mașini.
8. **Taxiurile din parcare:** liniile de intrare se pun departe de ieșirea din parcarea din dreapta, ca o mașină care iese din parcare să nu fie numărată ca sosire.
9. **Ieșiri:** `POST /api/vision` la fiecare secundă; în modul geamăn, `POST /api/spawn` la fiecare trecere de linie. Imaginea adnotată se servește ca MJPEG pe `:8001/stream` pentru panoul din dashboard.
10. **`demand_from_video.py`:** din sosirile pe tot clipul calculează vehicule pe oră pe direcție și le scrie în `flow`-urile din `routes.rou.xml` (Modulul 1).

### 12.5 Trei moduri, în ordinea priorității

| Mod | Ce face | Cost |
| --- | --- | --- |
| Calibrare | debitele măsurate din cameră devin traficul din simulare | ~1 h |
| Panou | cadrul cu detecții + cozile în dashboard, cu recomandarea AI-ului | +2 h |
| Geamăn | fiecare mașină reală care trece linia de intrare apare în ambele simulări | +1–2 h |

### 12.6 Confidențialitate

Nu se salvează și nu se afișează numere de înmatriculare sau fețe; se transmit doar cifre. Clipul de referință rămâne local și se șterge după hackathon, dacă așa ați convenit cu sursa. În dashboard și în slide-uri se menționează „Sursa imaginilor: WebcamRomania.ro”.

**Gata când:** pe un fragment de 2 minute, numărătoarea automată pe zona verde diferă cu mai puțin de 15% de una făcută de mână, iar mașinile parcate nu apar niciodată în cozi.

---

## 13. Contractul cu firmware-ul ESP32

Firmware-ul e scris de echipa de hardware; partea de IT trebuie doar să respecte protocolul din secțiunea 5 și să știe cum reacționează placa. Regula de bază: AI-ul recomandă, placa garantează siguranța.

**Stările plăcii**

| Stare | Intră când | Ce face | Iese când |
| --- | --- | --- | --- |
| `ASTEPTARE` | pornire | roșu general; LCD: „Aștept serverul” | 3 mesaje valide la rând → `AI` |
| `AI` | legătura e activă | aprinde faza `P`; la schimbare face galben `Y` ms și roșu general 500 ms | niciun mesaj valid 3 s sau `HB` blocat → `TRANZITIE` |
| `TRANZITIE` | legătura s-a pierdut | galben 3 s, apoi roșu general 2 s | gata → `AVARIE` |
| `AVARIE` | după tranziție | ciclu fix cu timpi reali; LCD: „MOD AVARIE – TIMPI FICȘI” | 3 heartbeat-uri valide la rând + sfârșit de ciclu → `REVENIRE` |
| `REVENIRE` | legătura a revenit | galben, roșu general 2 s | gata → `AI` |

**Reguli obligatorii**

- Înainte de orice scriere pe pini se verifică faptul că nu sunt două verzi în conflict. Dacă ar fi, placa aprinde roșu general.
- Liniile malformate sau mai lungi de 64 de caractere se ignoră; nu resetează timerul de legătură.
- În `AVARIE` galbenul e mereu 3 s, indiferent de `Y`.
- Fiecare mesaj valid primește `ACK:<HB>,L:<faza aprinsă>,S:<AI|AVARIE>`.

**Hardware de verificat cu echipa**

- Placa e alimentată separat (power bank pe 5V/VIN), ca scoaterea cablului de date să nu o stingă.
- LED-urile nu sunt pe GPIO 0, 2, 12 sau 15; LCD-ul I2C pe SDA 21 / SCL 22, adresa confirmată cu un scanner I2C.
- Numărul de grupuri de LED-uri = numărul de faze verzi ale intersecției A din Piața Unirii (vine din Modulul 1).
- Opțional: o machetă a Pieței Unirii (bulevard + strada laterală) pe care stau LED-urile, ca juriul să facă legătura cu camera.

---

## 14. Plan de lucru pe etape și ore

Lanțul complet cu max-pressure trebuie să meargă până la ora 7; tot ce urmează după e îmbunătățire. Orele sunt relative la startul hackathonului; Dev 3 e opțional.

**Înainte de hackathon (acasă):**

- [ ] Email trimis către WebcamRomania (anexa B)
- [ ] SUMO și toate librăriile instalate și testate pe laptopurile de demo, versiunile fixate
- [ ] Harta Pieței Unirii exportată din OSM; bulevardul și strada laterală identificate
- [ ] Capturi de ecran ale camerei la vârf de trafic (pentru zone); clipul de referință, dacă există acord
- [ ] Modelul YOLO descărcat; o antrenare de probă de 5 000 de pași rulată

| Ore | Dev 1 — simulare și AI | Dev 2 — server și frontend | Dev 3 — video | Hardware |
| --- | --- | --- | --- | --- |
| 0–1 | structura repo, `config.yaml`, contractele | `schemas.py`, `types.ts`, `mock.py` | `sources.py` (file + screen), `calibrate_zones.py` | montaj LED-uri, LCD |
| 1–3 | Modulul 1: harta Piața Unirii și rutele | dashboard pe mock | `detect.py`: crop + detecție + zone + excluderi | firmware: parsare + `ASTEPTARE` / `AI` |
| **Poarta 1 (ora 3)** | **rețea curată, recognoscibilă** | **pagina pe mock** | **cozi corecte pe clip, fără parcate** | **placa răspunde cu ACK** |
| 3–5 | `env_factory`, observație, recompensă, test de fum | `serial_bridge.py` cu placa reală | `demand_from_video.py` → rute calibrate | stările `TRANZITIE` / `AVARIE` / `REVENIRE` |
| 5–7 | pornește antrenarea (pe rutele calibrate); `max_pressure` | `sim_engine.py` + metrici, cu max-pressure | ieșirea spre `/api/vision`, stream MJPEG | teste de fail-safe |
| **Poarta 2 (ora 7)** | **lanțul cap-coadă merge: sumo-gui + dashboard + ESP32 live** | | | |
| 7–10 | `evaluate.py`, alegerea controlerului | Rush Hour, reset, heartbeat, evenimente, `CameraPanel` | panoul camerei în dashboard | machetă Piața Unirii |
| **Poarta 3 (ora 10)** | **controlerul final ales pe baza evaluării** | | | |
| 10–12 | `spillback_guard`; tramvai în SUMO (dacă e timp) | finisaj vizual, `run_demo` | modul geamăn (dacă e timp) | etichete pe machetă |
| **Freeze (ora 12)** | **nicio funcție nouă de aici** | | | |
| 12–14 | repetiții, înregistrarea video-ului de rezervă, slide-uri cu cifrele din evaluare | | | |

Dacă o poartă nu e atinsă, se taie din partea opțională, în ordine: tramvaiul, modul geamăn, panoul live (rămâne clipul), `spillback_guard`. Lanțul cap-coadă și fail-safe-ul nu se taie.

---

## 15. Testare, scenariul demo și planuri de rezervă

Fiecare modul are un test de fum care se rulează după orice schimbare; demo-ul se repetă de cel puțin 3 ori cap-coadă înainte de prezentare.

**Teste de fum**

- [ ] `python -m ai.env_factory --smoke`: un episod cu acțiuni aleatoare, fără erori
- [ ] `python -m ai.train --steps 5000`: salvează un model
- [ ] `python -m ai.evaluate --seeds 1 --controllers max_pressure`: produce `eval.csv`
- [ ] `python -m server.main --mock --no-serial` + pagina: grafic live, butoanele emit evenimente
- [ ] `python -m server.main --no-serial`: două simulări sincronizate 10 minute
- [ ] `python -m vision.detect --source file`: cozi pe clip, fără mașini parcate numărate
- [ ] Placa conectată: ONLINE; cablul de date scos: AVARIE în ≤ 3 s; repus: revine la AI

**Scenariul de pitch (4 minute)**

| Moment | Ce se arată | Ce faceți |
| --- | --- | --- |
| 0:00 | problema: semaforul orb și blocajul în lanț, cu o captură din Piața Unirii la vârf | slide |
| 0:40 | „ochii reali”: camera din Piața Unirii cu mașinile detectate și cozile numărate | panoul camerei |
| 1:10 | comparația live: stânga sumo-gui cu aceeași piață, dreapta graficul, LED-urile pe masă | nimic, doar explicați |
| 1:50 | Rush Hour: ambele linii urcă, cea verde coboară prima | tasta `R` |
| 2:40 | fail-safe: semaforul fizic trece singur pe avarie | scoateți cablul de date sau tasta `F` |
| 3:05 | revenirea fără salt brusc | repuneți cablul |
| 3:20 | cifrele din evaluare, costul, Faza 2 (ambulanță, tramvai) | slide |

**Planuri de rezervă**

| Dacă | Atunci |
| --- | --- |
| WebcamRomania nu răspunde sau refuză | filmare proprie a unei intersecții; harta se mută acolo |
| Internetul pică sau camera e offline | `vision.source: file` pe clipul înregistrat |
| Pitch-ul e după apus | clipul de zi, nu live-ul |
| PPO nu bate max-pressure | demo cu max-pressure, prezentat cinstit ca algoritm adaptiv |
| SUMO sau serverul crapă pe scenă | video-ul de rezervă, pitch-ul continuă |
| ESP32 nu se conectează | „Simulează căderea serverului” din dashboard + filmare cu placa |
| Detecția video numără prost | doar modul Calibrare (debite măsurate), fără panou live |
| Proiectorul are rezoluție mică | dashboard pe tot ecranul, sumo-gui pe al doilea monitor sau alternat |

---

## 16. Riscuri și întrebări de la juriu

**Riscuri tehnice principale**

| Risc | Prevenire |
| --- | --- |
| Integrarea de la final durează mult | lanțul cap-coadă până la ora 7, cu max-pressure |
| Conflicte de versiuni `sumo-rl` / `supersuit` / SB3 | instalare și test acasă, `requirements.txt` fixat |
| Teleportări SUMO care falsifică metricile | `--time-to-teleport -1` în ambele simulări |
| Gridlock la Rush Hour | numărul de vehicule reglat în M1 |
| Observație diferită între antrenare și demo | același `SumoEnvironment` în demo, completare cu zerouri identică |
| ESP32 se resetează la deschiderea portului | `dtr=False`, `rts=False` |
| Cablu USB doar de încărcare, driver lipsă | 2 cabluri testate, driver CP2102 / CH340 instalat |
| Laptopul nu duce YOLO + 2 simulări + browser | YOLO nano pe crop; video pe alt laptop dacă e nevoie |
| Mașini parcate numărate la coadă | zone `exclude` + poligoane strict pe carosabil |
| Internet slab la hackathon | totul instalat dinainte; video pe clip |

**Întrebări de la juriu și răspunsuri pregătite**

- *„Față de ce ați comparat?”* → Programul fix al intersecției, aceleași mașini, aceleași condiții, 5 seed-uri. Și separat față de un semafor cu senzori (`actuated`).
- *„Există deja sisteme adaptive, ce aduceți nou?”* → Sisteme adaptive există de zeci de ani (SCOOT, SCATS), dar sunt scumpe și închise. Noi aducem învățare automată, coordonare între intersecții, hardware ieftin și camere obișnuite, inclusiv cele deja montate în oraș.
- *„De unde știți câte mașini sunt?”* → Din camera reală din Piața Unirii: AI-ul vede doar ce vede camera, iar traficul din simulare e calibrat pe ea.
- *„Ce se întâmplă cu pietonii?”* → Verde maxim 60 s, deci nimeni nu așteaptă la infinit; trecerea de pietoni e în model.
- *„Și tramvaiul?”* → E în hartă ca extensie; prioritatea tramvaiului e în Faza 2.
- *„Ce se întâmplă dacă AI-ul greșește?”* → AI-ul doar recomandă. Controlerul local garantează galbenul, roșul general și interzice verzile conflictuale. Fail-safe-ul l-ați văzut.
- *„Diferența dintre simulare și realitate?”* → Traficul e calibrat din cameră; următorul pas e un pilot la o singură intersecție.
- *„Cât costă?”* → Pregătiți un calcul aproximativ: cameră (sau una existentă) + placă + montaj pe intersecție.
- *„Ce faceți cu imaginile?”* → Numărăm mașini, nu identificăm oameni sau numere și nu publicăm imaginile; sursa e menționată.

---

## 17. Faza 2

Doar pe slide, ca viziune; nu se implementează înainte de freeze.

- **Culoar de urgență:** când apare o ambulanță, semafoarele de pe traseul ei trec pe verde în avans.
- **Ocolirea accidentelor:** dacă o bandă se blochează, intersecția din spate oprește fluxul spre zona blocată.
- **Prioritatea tramvaiului:** relevantă direct pentru Piața Unirii — tramvaiul care se apropie primește verde, fără să blocheze traficul transversal mai mult decât e nevoie.

---

## 18. Cum dezvoltați cu Claude

Puneți acest fișier ca `PLAN.md` în rădăcina repo-ului, lângă el `CLAUDE.md` de mai jos, și `docs/zone_piata_unirii.jpg`. Lucrați câte un modul pe sesiune, cu commit după fiecare.

**`CLAUDE.md`**

```markdown
# Semafoare AI — reguli pentru Claude

- Planul complet e în PLAN.md. Citește secțiunea modulului la care lucrezi înainte să scrii cod.
- Contractele din PLAN.md §5 sunt fixe. Nu schimba câmpuri, nume sau formate fără să actualizezi
  simultan server/schemas.py, web/src/types.ts și PLAN.md, și fără să mă întrebi.
- Toate valorile configurabile vin din config.yaml. Nimic hardcodat (porturi, căi, praguri).
- TraCI se apelează doar din firul SimEngine. Comenzile din API trec printr-o coadă.
- Pentru sumo-rl, supersuit și stable-baselines3: verifică semnăturile în pachetele instalate
  (site-packages) înainte să le folosești; nu te baza pe exemple vechi.
- Fiecare modul are un mod --mock sau --smoke și un test de fum rulabil dintr-o comandă.
- Nu instala și nu actualiza pachete fără să-mi spui; versiunile sunt în requirements.txt.
- Modulul video nu extrage fluxul camerei din player și nu salvează cadre; sursa implicită e clipul local.
- Texte afișate utilizatorului: în română. Codul și comentariile: în engleză sau română, consecvent.
- După fiecare modul: rulează testul de fum și spune-mi exact ce a mers și ce nu.
```

**Ordinea sesiunilor și primul prompt pentru fiecare**

1. **Schelet.** „Citește PLAN.md și CLAUDE.md. Creează structura din §4, `config.yaml`, `requirements.txt` și contractele din §5 în `server/schemas.py` și `web/src/types.ts`. Fără logică încă.”
2. **Mock + frontend.** „Implementează `server/mock.py` și `server/main.py` în modul `--mock` (§10), apoi dashboard-ul din §11 în `web/`. Pornește pe mock și verifică toate zonele paginii.”
3. **Harta.** „Scrie `scripts/build_net` și un `routes.rou.xml` conform §6 pentru rețeaua Pieței Unirii din `sumo/`. Rulează simularea fără interfață și raportează teleportările și coada maximă.”
4. **Mediul RL.** „Implementează `ai/env_factory.py`, `ai/observation.py`, `ai/reward.py` din §7 și testul `--smoke`. Verifică întâi atributele `TrafficSignal` în `sumo-rl` instalat.”
5. **Antrenare.** „Implementează `ai/train.py` din §7 și rulează 5 000 de pași. Apoi pornește antrenarea completă în fundal.”
6. **Controlere și evaluare.** „Implementează `controllers/` și `ai/evaluate.py` din §8. Rulează evaluarea pentru `fixed` și `max_pressure`.”
7. **Motorul de simulare.** „Implementează `server/sim_engine.py` și `server/metrics.py` din §9, cu `max_pressure`. Pornește serverul fără serial și verifică sincronizarea timp de 10 minute.”
8. **Puntea serială.** „Implementează `server/serial_bridge.py` din §10, plus `scripts/fake_esp.py`. Testează reconectarea și `/api/heartbeat`.”
9. **Video.** „Implementează `vision/` din §12: `sources.py` (file și screen), `calibrate_zones.py` care pornește de la anexa A, `detect.py` cu crop, zone, excluderi și pragul relativ de oprire. Rulează pe clipul din `vision/clips/` și raportează numărătoarea pe primele 2 minute.”
10. **Calibrare.** „Implementează `vision/demand_from_video.py` din §12.4 și actualizează `flow`-urile din `routes.rou.xml`.”
11. **Demo.** „Scrie `scripts/run_demo` care pornește serverul, modulul video și deschide pagina dintr-o singură comandă.”

**Sfaturi**

- Lipiți erorile exact cum apar, cu tot traceback-ul, nu rezumate.
- Cereți întâi un plan scurt pentru modul, aprobați-l, apoi codul.
- Pentru frontend, cereți explicit ca pagina să fie verificată la 960×1080 și la 1280×720.
- Pentru video, dați-i lui Claude un cadru din clip și `docs/zone_piata_unirii.jpg`, ca să poată verifica zonele vizual.
- Dacă o sesiune se lungește și Claude începe să rescrie lucruri deja făcute, închideți-o și porniți una nouă de la PLAN.md.

---

## Anexa A — `vision/zones.json` inițial

Coordonate normalizate (0–1) față de cadrul complet, estimate pe captura de 2144×1240 din `docs/zone_piata_unirii.jpg`. Sunt un punct de plecare; se corectează în `calibrate_zones.py`.

```json
{
  "coords": "normalized",
  "reference_frame": [2144, 1240],
  "crop": [0.466, 0.266, 0.938, 0.980],
  "lanes": [
    {
      "id": "blv_dir1",
      "label": "Bulevard, direcția care se îndepărtează (coada vizibilă)",
      "role": "queue",
      "polygon": [[0.547, 0.419], [0.589, 0.419], [0.875, 0.972], [0.709, 0.972]]
    },
    {
      "id": "blv_dir2",
      "label": "Bulevard, direcția spre cameră (doar sosiri)",
      "role": "arrivals",
      "polygon": [[0.513, 0.419], [0.547, 0.419], [0.709, 0.972], [0.603, 0.972]]
    },
    {
      "id": "lateral",
      "label": "Strada laterală din dreapta",
      "role": "queue",
      "polygon": [[0.616, 0.464], [0.728, 0.379], [0.788, 0.407], [0.667, 0.528]]
    }
  ],
  "stop_line": {"a": [0.504, 0.397], "b": [0.578, 0.397]},
  "entry_lines": [
    {"approach": "blv_dir1", "a": [0.688, 0.900], "b": [0.837, 0.900]},
    {"approach": "blv_dir2", "a": [0.534, 0.550], "b": [0.585, 0.550]},
    {"approach": "lateral",  "a": [0.715, 0.395], "b": [0.770, 0.420]}
  ],
  "exclude": [
    {"id": "parcare_dreapta", "polygon": [[0.739, 0.484], [0.975, 0.516], [0.975, 0.976], [0.879, 0.976]]},
    {"id": "parcare_stanga_jos", "polygon": [[0.000, 0.766], [0.354, 0.871], [0.354, 0.976], [0.000, 0.976]]},
    {"id": "parcate_jos_centru", "polygon": [[0.382, 0.887], [0.499, 0.887], [0.499, 0.976], [0.382, 0.976]]}
  ],
  "ignore_classes": ["person", "train"],
  "stopped": {"window_s": 2.0, "max_move_rel_height": 0.15}
}
```

---

## Anexa B — Email către WebcamRomania

Contact de pe pagina camerei: webcamromania2018@gmail.com, tel. 0751 478 912 (răspuns în maximum 24 h, conform site-ului).

**Subiect:** Acord pentru folosirea imaginilor camerei Piața Unirii Iași într-un proiect de hackathon

> Bună ziua,
>
> Suntem o echipă de studenți care participă la hackathonul [NUME], pe [DATA]. Construim un prototip de semafoare inteligente: un sistem care numără mașinile de la o intersecție și adaptează culorile semafoarelor ca să reducă timpul de așteptare.
>
> Am dori să folosim imaginile camerei din Piața Unirii, Iași, astfel:
>
> - procesăm cadrele pe laptop doar pentru a număra vehiculele de pe carosabil;
> - nu publicăm și nu redistribuim imaginile; nu identificăm persoane sau numere de înmatriculare;
> - în prezentare menționăm clar sursa: WebcamRomania.ro.
>
> V-am ruga, dacă sunteți de acord:
>
> 1. să ne confirmați că putem folosi imaginile în acest scop;
> 2. să ne permiteți o înregistrare de test de aproximativ 15 minute, folosită doar intern și ștearsă după hackathon;
> 3. dacă e posibil, să ne indicați un link direct către flux, ca să nu încărcăm playerul de pe site.
>
> Vă mulțumim și vă putem trimite după eveniment o scurtă prezentare a rezultatelor.
>
> Cu stimă,
> [NUME], [ROL în echipă]
> [TELEFON] · [EMAIL]
