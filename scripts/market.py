"""市場データ: Stooqの日足CSV取得・統計・SVGチャート生成。
（旧FRED版は GitHub Actions のIPからだと応答がなくタイムアウトし続けたため、
 CSVダウンロードが用途として公開されている Stooq に切り替えた）"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import urllib.request
from pathlib import Path

from common import DATA_DIR, load_config

# 内部の系列ID（旧FREDのID。サイト側のCSVファイル名・テンプレートで使用中のため維持）
# → Stooqのティッカーシンボルへの対応表
STOOQ_SYMBOLS = {
    "SP500": "^spx",
    "NASDAQCOM": "^ndq",
    "NIKKEI225": "^nkx",
    "DEXJPUS": "usdjpy",
}
STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&d1={start}&d2={end}&i=d"


def market_dir() -> Path:
    return Path(os.environ.get("MARKET_DIR") or (DATA_DIR / "market"))


def parse_fred_csv(text: str, series_id: str) -> list[tuple[str, float]]:
    """自前保存CSV（DATE,<ID>。欠損は '.' または空）を [(日付, 値)] にする。
    ファイル名・ヘッダー形式は旧FRED時代のまま踏襲しているだけで、
    取得元がFREDかどうかとは無関係（load_series/save_series が使用）。"""
    rows: list[tuple[str, float]] = []
    reader = csv.reader(io.StringIO(text.strip()))
    header = next(reader, None)
    if not header or len(header) < 2:
        raise ValueError("CSVヘッダーが不正です")
    for r in reader:
        if len(r) < 2:
            continue
        d, v = r[0].strip(), r[1].strip()
        if not v or v == ".":
            continue
        try:
            dt.date.fromisoformat(d)
            rows.append((d, float(v)))
        except ValueError:
            continue
    return rows


def parse_stooq_csv(text: str) -> list[tuple[str, float]]:
    """Stooqの日足CSV（Date,Open,High,Low,Close,Volume）から終値を [(日付, 値)] にする。"""
    stripped = text.strip()
    if not stripped or stripped.startswith("<"):
        raise ValueError("Stooqから想定外の応答（HTML等）")
    rows: list[tuple[str, float]] = []
    reader = csv.reader(io.StringIO(stripped))
    header = next(reader, None)
    if not header or len(header) < 2:
        raise ValueError("CSVヘッダーが不正です")
    lower = [h.strip().lower() for h in header]
    if "date" not in lower or "close" not in lower:
        raise ValueError(f"想定外のCSV形式です: {header}")
    i_date, i_close = lower.index("date"), lower.index("close")
    for r in reader:
        if len(r) <= max(i_date, i_close):
            continue
        d, v = r[i_date].strip(), r[i_close].strip()
        if not v or v.upper() == "N/D":
            continue
        try:
            dt.date.fromisoformat(d)
            rows.append((d, float(v)))
        except ValueError:
            continue
    return rows


def load_series(series_id: str) -> list[tuple[str, float]]:
    p = market_dir() / f"{series_id}.csv"
    if not p.exists():
        return []
    return parse_fred_csv(p.read_text(encoding="utf-8"), series_id)


def save_series(series_id: str, rows: list[tuple[str, float]], keep: int) -> None:
    d = market_dir()
    d.mkdir(parents=True, exist_ok=True)
    merged = sorted(dict(rows).items())[-keep:]
    with open(d / f"{series_id}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["DATE", series_id])
        w.writerows(merged)


def fetch_series(series_id: str, days: int = 800, timeout: int = 20) -> list[tuple[str, float]]:
    """Stooqの日足CSVを取得する（実ブラウザに近いヘッダーで、失敗時は最大3回リトライ）。"""
    symbol = STOOQ_SYMBOLS.get(series_id)
    if not symbol:
        raise ValueError(f"Stooq未対応の系列IDです: {series_id}")
    start = (dt.date.today() - dt.timedelta(days=days)).strftime("%Y%m%d")
    end = dt.date.today().strftime("%Y%m%d")
    url = STOOQ_URL.format(symbol=symbol, start=start, end=end)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/csv,text/plain,*/*",
        "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
        "Referer": "https://stooq.com/",
        "Connection": "close",
    }
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return parse_stooq_csv(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 - リトライのため一旦捕捉
            last_err = e
    raise last_err  # type: ignore[misc]


def _pct(a: float, b: float) -> float | None:
    return None if not b else (a / b - 1) * 100


def stats(rows: list[tuple[str, float]]) -> dict | None:
    """最新値と期間別騰落率、直近1年高値からの下落率。"""
    if len(rows) < 3:
        return None
    last_d, last_v = rows[-1]
    last_date = dt.date.fromisoformat(last_d)
    prev_v = rows[-2][1] if len(rows) >= 2 else None

    def back(days: int):
        target = last_date - dt.timedelta(days=days)
        cand = [v for d, v in rows if dt.date.fromisoformat(d) <= target]
        return cand[-1] if cand else None

    year = [v for d, v in rows if dt.date.fromisoformat(d) > last_date - dt.timedelta(days=365)]
    hi = max(year) if year else last_v
    ytd_base = [v for d, v in rows if dt.date.fromisoformat(d) < dt.date(last_date.year, 1, 1)]
    return {
        "date": last_d,
        "last": last_v,
        "chg_1d": _pct(last_v, prev_v) if prev_v else None,
        "chg_1w": _pct(last_v, back(7)) if back(7) else None,
        "chg_1m": _pct(last_v, back(30)) if back(30) else None,
        "chg_3m": _pct(last_v, back(91)) if back(91) else None,
        "chg_1y": _pct(last_v, back(365)) if back(365) else None,
        "chg_ytd": _pct(last_v, ytd_base[-1]) if ytd_base else None,
        "from_high": _pct(last_v, hi),
        "high_1y": hi,
    }


def svg_line_chart(rows: list[tuple[str, float]], title: str, w: int = 640, h: int = 220) -> str:
    """依存ライブラリなしのアクセシブルな折れ線SVG。色はCSS変数で追従。"""
    pts = rows[-260:]
    if len(pts) < 2:
        return ""
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad
    L, R, T, B = 8, 8, 12, 24
    iw, ih = w - L - R, h - T - B

    def x(i):
        return L + iw * i / (len(pts) - 1)

    def y(v):
        return T + ih * (1 - (v - lo) / (hi - lo))

    path = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(pts))
    area = f"{path} L{x(len(pts)-1):.1f},{T+ih:.1f} L{x(0):.1f},{T+ih:.1f} Z"
    grid = "".join(
        f'<line x1="{L}" x2="{w-R}" y1="{T+ih*k/4:.1f}" y2="{T+ih*k/4:.1f}" class="c-grid"/>' for k in range(5)
    )
    first, last = pts[0], pts[-1]
    desc = f"{first[0]}から{last[0]}までの推移。始値{first[1]:,.1f}、最新{last[1]:,.1f}、期間内の最高{max(vals):,.1f}、最低{min(vals):,.1f}。"
    return (
        f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-labelledby="t d" preserveAspectRatio="xMidYMid meet">'
        f'<title id="t">{title}</title><desc id="d">{desc}</desc>{grid}'
        f'<path d="{area}" class="c-area"/><path d="{path}" class="c-line" fill="none"/>'
        f'<circle cx="{x(len(pts)-1):.1f}" cy="{y(last[1]):.1f}" r="3.5" class="c-dot"/>'
        f'<text x="{L}" y="{h-6}" class="c-txt">{first[0]}</text>'
        f'<text x="{w-R}" y="{h-6}" class="c-txt" text-anchor="end">{last[0]}</text></svg>'
    )


def monthly_path(series_id: str) -> Path:
    return market_dir() / f"{series_id}_monthly.csv"


def load_monthly_series(series_id: str) -> list[tuple[str, float]]:
    """積立の疑似体験（過去データ）用の月次データ。"""
    p = monthly_path(series_id)
    if not p.exists():
        return []
    return parse_fred_csv(p.read_text(encoding="utf-8"), series_id)


def save_monthly_series(series_id: str, rows: list[tuple[str, float]]) -> None:
    d = market_dir()
    d.mkdir(parents=True, exist_ok=True)
    merged = sorted(dict(rows).items())
    with open(monthly_path(series_id), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["DATE", series_id])
        w.writerows(merged)


def resample_monthly(rows: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """日次の [(date, value)] を、各月の最後に取得できた値で月次化する（各月1日の日付で表す）。"""
    by_month: dict[str, float] = {}
    for d, v in sorted(rows):
        by_month[d[:7]] = v  # ソート済みなので、同じ月では最後に代入された値が残る
    return [(f"{ym}-01", v) for ym, v in sorted(by_month.items())]


def all_market() -> list[dict]:
    """設定順にデータを読み、統計とチャートを付けて返す。データ無しの系列も枠は返す。"""
    out = []
    for s in load_config()["market"]["series"]:
        rows = load_series(s["id"])
        out.append({**s, "rows": rows, "stats": stats(rows), "svg": svg_line_chart(rows, s["name"])})
    return out
