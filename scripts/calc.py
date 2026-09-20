"""NISAの数字計算（サイト内の表とシミュレーターで共通の前提）。

前提: 毎月末に積立、年利は月複利 (年利/12)、税・為替・手数料の変動は考慮しない。
将来の運用成果を予測・保証するものではなく、前提を置いた計算結果にすぎない。
"""
from __future__ import annotations

LIFETIME_CAP = 18_000_000        # 非課税保有限度額（簿価ベース）
GROWTH_SUBCAP = 12_000_000       # うち成長投資枠の上限
TSUMITATE_ANNUAL = 1_200_000     # つみたて投資枠 年間
GROWTH_ANNUAL = 2_400_000        # 成長投資枠 年間
TOTAL_ANNUAL = TSUMITATE_ANNUAL + GROWTH_ANNUAL  # 3,600,000


def future_value(monthly: float, annual_rate: float, years: float, initial: float = 0.0) -> float:
    """毎月積立の将来価値。annual_rate は 0.05 のような小数。"""
    n = int(round(years * 12))
    r = annual_rate / 12
    if r == 0:
        return initial + monthly * n
    g = (1 + r) ** n
    return initial * g + monthly * ((g - 1) / r)


def principal(monthly: float, years: float, initial: float = 0.0) -> float:
    return initial + monthly * int(round(years * 12))


def years_to_fill(monthly: float, cap: float = LIFETIME_CAP) -> float:
    """簿価ベースの生涯投資枠を使い切るまでの年数（年間上限は別途考慮）。"""
    annual = min(monthly * 12, TOTAL_ANNUAL)
    return cap / annual


def net_rate(gross: float, fee: float) -> float:
    """信託報酬を年率で単純に差し引いた実質利回り（近似）。"""
    return gross - fee


def yen_man(v: float) -> str:
    """円 -> 「1,234万円」表記（万円未満四捨五入）。"""
    return f"{round(v / 10_000):,}万円"


def fmt_years(y: float) -> str:
    return f"{y:.1f}年" if abs(y - round(y)) > 1e-9 else f"{int(round(y))}年"


def fill_plan(yearly: float, done: float = 0.0) -> dict:
    """年間投資額(想定)と投資済み簿価から、生涯枠1,800万円を使い切るまでの年数を求める。
    年間上限360万円・つみたて年120万円・成長年240万円・成長の生涯上限1,200万円を反映。
    簡略化: 投資済み額の内訳（つみたて/成長）は考慮せず、全体の残枠だけを減らす。
    """
    y = min(yearly, TOTAL_ANNUAL)
    t = min(y, TSUMITATE_ANNUAL)
    g = max(0.0, y - t)
    remain = max(0.0, LIFETIME_CAP - done)
    if remain == 0 or y <= 0:
        return {"annual": y, "tsumitate": t, "growth": g, "years": 0.0 if remain == 0 else float("inf"), "capped": yearly > TOTAL_ANNUAL}
    if g == 0:
        years = remain / t
    else:
        y_g = GROWTH_SUBCAP / g          # 成長投資枠が埋まるまで
        if y_g * y >= remain:
            years = remain / y
        else:
            years = y_g + (remain - y_g * y) / t
    return {"annual": y, "tsumitate": t, "growth": g, "years": years, "capped": yearly > TOTAL_ANNUAL}
