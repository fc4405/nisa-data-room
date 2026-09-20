#!/usr/bin/env python3
"""FREDから市場データを取得して data/market/*.csv を更新する。
失敗した系列は既存データをそのまま残す（サイトは壊れない）。"""
import sys

from common import load_config
from market import fetch_series, load_series, save_series


def main() -> int:
    cfg = load_config()["market"]
    ok = 0
    for s in cfg["series"]:
        try:
            new = fetch_series(s["id"])
            if not new:
                raise ValueError("空のデータ")
            merged = dict(load_series(s["id"]))
            merged.update(dict(new))
            save_series(s["id"], list(merged.items()), cfg.get("keep_rows", 520))
            print(f"OK   {s['id']}: {len(new)}行 (最新 {new[-1][0]})")
            ok += 1
        except Exception as e:  # noqa: BLE001 - 1系列の失敗で全体を止めない
            print(f"SKIP {s['id']}: {e}", file=sys.stderr)
    print(f"{ok}/{len(cfg['series'])} 系列を更新")
    return 0  # 取得失敗でもワークフローは継続


if __name__ == "__main__":
    sys.exit(main())
