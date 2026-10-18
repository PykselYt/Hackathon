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
- Texte afișate utilizatorului: în română. Codul și comentariile: în engleză.
- După fiecare modul: rulează testul de fum și spune-mi exact ce a mers și ce nu.

## Mediu

- `source scripts/env.sh` (bash sau zsh) activează `.venv` (Python 3.11, creat cu uv) și setează `SUMO_HOME`.
- Pachetele se instalează cu `uv pip install --python .venv/bin/python …` (venv-ul nu are pip).
- Rețeaua se generează din `sumo/src/*.xml` cu `scripts/build_net.sh`; nu edita `sumo/net*.net.xml` de mână.
- Rutele se generează cu `python scripts/gen_routes.py`; verificarea rețelei: `python scripts/check_net.py --rush 80`.
- `sumo-gui` pe macOS are nevoie de XQuartz.

## Windows

- O singură dată: `setup_windows.bat` (creează `.venv` pentru Windows, instalează `requirements.txt`, reinstalează `web/node_modules`).
  Un `.venv` copiat de pe macOS e redenumit în `.venv_macos`.
- Pornire: `run_mock.bat` (fără SUMO) sau `run_demo.bat [--no-serial | --serial-port COM5]`.
- În cmd, `call scripts\env.bat` e echivalentul lui `source scripts/env.sh`; rețeaua: `scripts\build_net.bat`.
- `scripts/fake_esp.py` folosește un pty Unix și nu merge pe Windows.
