"""記事内ショートコード（{{table:xxx}} など）の実体。ビルド時に計算するので常に前提と整合する。"""
from __future__ import annotations

import html

import calc
from market import all_market

ASSUME = (
    '<p class="table-note">前提: 毎月末に積立、年利は月複利、税・為替・手数料の変動は考慮しない単純計算です。'
    "将来の運用成果を予測・保証するものではありません。</p>"
)


def _table(head: list[str], rows: list[list[str]], caption: str) -> str:
    th = "".join(f"<th scope='col'>{html.escape(h)}</th>" for h in head)
    def cell(i: int, c: str) -> str:
        c = html.escape(c)
        return f'<th scope="row">{c}</th>' if i == 0 else f"<td>{c}</td>"

    trs = "".join("<tr>" + "".join(cell(i, c) for i, c in enumerate(r)) + "</tr>" for r in rows)
    return (
        f'<div class="table-wrap"><table><caption>{html.escape(caption)}</caption>'
        f"<thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>"
    )


def table_fill_years() -> str:
    rows = []
    for man in (3, 5, 8, 10, 15, 20, 30):
        m = man * 10_000
        annual = min(m * 12, calc.TOTAL_ANNUAL)
        y = calc.years_to_fill(m)
        only_tsumi = "可能" if m * 12 <= calc.TSUMITATE_ANNUAL else "つみたて枠だけでは不可"
        rows.append([f"月{man}万円", f"{annual // 10_000:,}万円", calc.fmt_years(y), only_tsumi])
    return _table(
        ["毎月の投資額", "年間投資額", "1,800万円を使い切る年数", "つみたて投資枠のみで投資可能か"],
        rows,
        "毎月の投資額別・生涯投資枠（簿価1,800万円）を使い切るまでの年数",
    ) + '<p class="table-note">生涯投資枠は購入時の取得価額（簿価）で管理されるため、運用成績（利回り）に関係なく、投資した元本の累計で決まります。年間の投資上限は360万円です。</p>'


def table_fv(rate_pct: float) -> str:
    rate = rate_pct / 100
    years = (10, 20, 30)
    head = ["毎月の積立額"] + [f"{y}年後" for y in years] + ["（参考）30年の元本"]
    rows = []
    for man in (1, 3, 5, 10):
        m = man * 10_000
        rows.append(
            [f"月{man}万円"]
            + [calc.yen_man(calc.future_value(m, rate, y)) for y in years]
            + [calc.yen_man(calc.principal(m, 30))]
        )
    return _table(head, rows, f"年利{rate_pct:g}%で積み立てた場合の評価額（前提つき計算）") + ASSUME


def table_fee_impact() -> str:
    monthly, years, gross = 30_000, 30, 0.05
    base = calc.future_value(monthly, calc.net_rate(gross, 0.001), years)
    rows = []
    for fee in (0.001, 0.005, 0.01, 0.015):
        v = calc.future_value(monthly, calc.net_rate(gross, fee), years)
        diff = "―" if fee == 0.001 else f"-{calc.yen_man(base - v)}"
        rows.append([f"{fee*100:.1f}%", calc.yen_man(v), diff])
    return _table(
        ["年間コスト（信託報酬）", "30年後の評価額", "コスト0.1%との差"],
        rows,
        "月3万円を30年、運用前の年利5%と仮定したときのコストの影響",
    ) + ASSUME


def market_summary(sid: str) -> str:
    for m in all_market():
        if m["id"] == sid:
            return m["svg"] or '<p class="table-note">データ取得待ちです。</p>'
    return ""


def fmt_pct(v):
    return "―" if v is None else f"{v:+.1f}%"


def market_table() -> str:
    rows = []
    for m in all_market():
        s = m["stats"]
        if not s:
            rows.append([m["name"], "取得待ち", "―", "―", "―", "―", "―"])
            continue
        rows.append(
            [m["name"], f"{s['last']:,.2f}", fmt_pct(s["chg_1w"]), fmt_pct(s["chg_1m"]),
             fmt_pct(s["chg_3m"]), fmt_pct(s["chg_1y"]), fmt_pct(s["from_high"])]
        )
    return _table(
        ["指標", "最新値", "1週間", "1か月", "3か月", "1年", "直近1年高値から"],
        rows,
        "主要指標の最新値と騰落率（自動更新）",
    )


TABLES = {
    "fill_years": table_fill_years,
    "fv_3": lambda: table_fv(3),
    "fv_5": lambda: table_fv(5),
    "fee_impact": table_fee_impact,
    "market_table": market_table,
}
