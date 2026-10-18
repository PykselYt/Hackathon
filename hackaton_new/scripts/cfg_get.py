"""Prints one value of config.yaml for the Windows .bat scripts, e.g. `python scripts/cfg_get.py server.port`."""
import sys
from pathlib import Path

import yaml

cfg = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml").read_text(encoding="utf-8"))
for key in sys.argv[1].split("."):
    cfg = cfg[key]
print(cfg)
