#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yaml

DATASET_APPS = {
    "LightSystem", "LightTalk", "LightShop", "LightWeather",
    "LightFlight", "LightStock", "LightNews",
}
UTILITY_KEEP = {
    "MathServer", "UnitServer", "OSINTServer", "TimeServer", "LangServer",
    "CryptoServer", "GraphServer", "ChemServer", "URLServer", "CSVServer",
    "JSONServer", "DiffServer", "HashServer", "ColorServer", "EncodingServer",
    "BarcodeServer", "CurrencyServer", "RandomServer", "TemplateServer",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=Path("config/general.yaml"))
    ap.add_argument("--backup-suffix", default=".bak")
    args = ap.parse_args()

    cfg_path: Path = args.config
    bak_path = cfg_path.with_suffix(cfg_path.suffix + args.backup_suffix)
    if not bak_path.exists():
        shutil.copy2(cfg_path, bak_path)
        print(f"[narrow] backup created: {bak_path}", file=sys.stderr)

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    keep = DATASET_APPS | UTILITY_KEEP
    util_on = sandbox_on = 0
    for s in cfg["servers"]:
        s["use"] = s["name"] in keep
        if s["use"] and s.get("use_sandbox"):
            sandbox_on += 1
        elif s["use"]:
            util_on += 1

    with open(cfg_path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    print(f"[narrow] utility_enabled={util_on} sandbox_enabled={sandbox_on}", file=sys.stderr)


if __name__ == "__main__":
    main()
