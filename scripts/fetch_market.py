#!/usr/bin/env python3
"""FREDから市場データを取得して data/market/*.csv を更新する。
失敗した系列は既存データをそのまま残す（サイトは壊れない）。"""
import sys

from common import load_config
from market import fetch_series, load_monthly_series, load_series, resample_monthly, save_monthly_series, save_series

MONTHLY_HISTORY_DAYS = 6200  # 約17年分。「積立の疑似体験」ツール用の長期データ


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

    # 「積立の疑似体験」ツール用: 長期の月次データ（取得に失敗しても daily-publish は止めない）
    for s in cfg["series"]:
        try:
            long_rows = fetch_series(s["id"], days=MONTHLY_HISTORY_DAYS)
            if not long_rows:
                raise ValueError("空のデータ")
            monthly = resample_monthly(long_rows)
            merged_m = dict(load_monthly_series(s["id"]))
            merged_m.update(dict(monthly))
            save_monthly_series(s["id"], list(merged_m.items()))
            span = f"{monthly[0][0]}〜{monthly[-1][0]}" if monthly else "―"
            print(f"OK   {s['id']} 月次（体験用）: {len(monthly)}か月分 ({span})")
        except Exception as e:  # noqa: BLE001
            print(f"SKIP {s['id']} 月次（体験用）: {e}", file=sys.stderr)
    return 0  # 取得失敗でもワークフローは継続


if __name__ == "__main__":
    sys.exit(main())
