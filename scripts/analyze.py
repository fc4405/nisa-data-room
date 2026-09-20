#!/usr/bin/env python3
"""週次の自己点検・分析レポートを作る。

出力: data/analytics.json（記事生成のトピック提案が参照） / reports/weekly.md（人が読むレポート）

見るもの:
  1. 記事の在庫・古さ・内部リンクの孤立（サイト内で完結する点検）
  2. data/facts.yaml の鮮度（90日以上前に確認した事実は要再確認）
  3. 自動生成の成否（不採用になったトピックと理由）
  4. Google Search Console（環境変数が設定されている場合のみ）
  5. 収益（data/revenue.csv に手入力した月次の報酬額 → 月5万円に対する進捗）
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from common import ROOT, load_articles, load_yaml, today_jst, to_date  # noqa: E402

STALE_DAYS = 180
FACT_STALE_DAYS = 90
TARGET_YEN = 50_000


def inventory() -> dict:
    arts = load_articles(include_future=True)
    inbound = {a["slug"]: 0 for a in arts}
    for a in arts:
        for slug in set(re.findall(r"\]\(/articles/([a-z0-9\-]+)/\)", a["body"])):
            if slug in inbound and slug != a["slug"]:
                inbound[slug] += 1
    today = today_jst()
    stale = [a["slug"] for a in arts if (today - a["updated"]).days > STALE_DAYS]
    orphans = [s for s, n in inbound.items() if n == 0]
    return {"count": len(arts), "stale": stale, "orphans": orphans,
            "chars": sum(len(re.sub(r"\s+", "", a["body"])) for a in arts)}


def facts_freshness() -> list[str]:
    today = today_jst()
    out = []
    for f in load_yaml(common.DATA_DIR / "facts.yaml")["facts"]:
        age = (today - to_date(f["verified_at"])).days
        if age > FACT_STALE_DAYS:
            out.append(f"{f['id']}（{age}日前）")
    return out


def generation_summary() -> dict:
    p = common.DATA_DIR / "generation_log.json"
    log = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    bad = {k: v.get("reasons") or v.get("last_result") for k, v in log.items()
           if v.get("last_result") not in (None, "published")}
    drafts = sorted(x.stem for x in common.DRAFTS_DIR.glob("*.md")) if common.DRAFTS_DIR.exists() else []
    return {"attempted": len(log), "problems": bad, "drafts": drafts}


def fetch_gsc(days: int = 28) -> dict | None:
    key, site = os.environ.get("GSC_SERVICE_ACCOUNT_JSON"), os.environ.get("GSC_SITE_URL")
    if not key or not site:
        return None
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
    except ImportError:
        print("google-auth が未インストールのためSearch Consoleをスキップ", file=sys.stderr)
        return None
    creds = service_account.Credentials.from_service_account_info(
        json.loads(key), scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    sess = AuthorizedSession(creds)
    url = f"https://searchconsole.googleapis.com/webmasters/v3/sites/{quote(site, safe='')}/searchAnalytics/query"
    end = today_jst() - dt.timedelta(days=3)  # 直近数日は確定前
    start = end - dt.timedelta(days=days)
    res = {}
    for dim in ("page", "query"):
        r = sess.post(url, json={"startDate": start.isoformat(), "endDate": end.isoformat(),
                                 "dimensions": [dim], "rowLimit": 200}, timeout=60)
        r.raise_for_status()
        res[dim] = [{"key": x["keys"][0], "clicks": x["clicks"], "impressions": x["impressions"],
                     "ctr": x["ctr"], "position": x["position"]} for x in r.json().get("rows", [])]
    pages = res["page"]
    res["low_ctr_pages"] = [p for p in pages if p["impressions"] >= 50 and p["ctr"] < 0.02][:10]
    res["near_page1_queries"] = [q for q in res["query"] if 8 <= q["position"] <= 20 and q["impressions"] >= 20][:15]
    res["totals"] = {"clicks": sum(p["clicks"] for p in pages), "impressions": sum(p["impressions"] for p in pages)}
    return res


def revenue() -> dict:
    p = common.DATA_DIR / "revenue.csv"
    if not p.exists():
        return {}
    by_month: dict[str, int] = {}
    with open(p, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                by_month[row["month"]] = by_month.get(row["month"], 0) + int(row["amount_yen"])
            except (KeyError, ValueError):
                continue
    return dict(sorted(by_month.items()))


def render_report(inv, stale_facts, gen, gsc, rev) -> str:
    L = [f"# 週次レポート {today_jst().isoformat()}", ""]
    L += ["## サマリー", f"- 公開記事: {inv['count']}本（合計 約{inv['chars']:,}字）",
          f"- 半年以上更新していない記事: {len(inv['stale'])}本", f"- 内部リンクが1本も向いていない記事: {len(inv['orphans'])}本", ""]
    if inv["orphans"]:
        L += ["### 内部リンクの孤立記事（他の記事から1本もリンクされていない）"] + [f"- {s}" for s in inv["orphans"]] + [""]
    if inv["stale"]:
        L += ["### 更新が古い記事"] + [f"- {s}" for s in inv["stale"]] + [""]
    L += ["## 事実データの鮮度（data/facts.yaml）"]
    L += [f"- 要再確認: {', '.join(stale_facts)}" if stale_facts else "- すべて90日以内に確認済み", ""]
    L += ["## 自動生成の状況", f"- 試行したトピック: {gen['attempted']}件"]
    if gen["problems"]:
        L += ["- 公開に至らなかったもの:"] + [f"  - {k}: {v}" for k, v in gen["problems"].items()]
    if gen["drafts"]:
        L += [f"- content/drafts/ にある下書き: {', '.join(gen['drafts'])}（目視確認のうえ、問題なければ content/articles/ へ移動して公開）"]
    L += [""]
    L += ["## 検索流入（Search Console 直近28日）"]
    if gsc:
        t = gsc["totals"]
        L += [f"- クリック {t['clicks']:,} / 表示 {t['impressions']:,}"]
        if gsc["low_ctr_pages"]:
            L += ["- 表示は多いのにクリック率が低いページ（タイトル・説明文の見直し候補）:"] + [
                f"  - {p['key']}（表示{p['impressions']} / CTR {p['ctr']*100:.1f}%）" for p in gsc["low_ctr_pages"]]
        if gsc["near_page1_queries"]:
            L += ["- 検索順位8〜20位のキーワード（記事の強化で1ページ目を狙える候補）:"] + [
                f"  - {q['key']}（順位{q['position']:.1f} / 表示{q['impressions']}）" for q in gsc["near_page1_queries"]]
    else:
        L += ["- 未接続（SETUP.md の「Search Console連携」を参照。設定すると、伸びしろのあるキーワードが自動でトピック提案に反映されます）"]
    L += ["", "## 収益（data/revenue.csv の手入力値）"]
    if rev:
        for m, y in list(rev.items())[-6:]:
            L += [f"- {m}: {y:,}円（目標 {TARGET_YEN:,}円の {y / TARGET_YEN * 100:.0f}%）"]
    else:
        L += ["- 未入力。ASPの管理画面で確定した報酬を、月に1回 data/revenue.csv（month,source,amount_yen）に追記すると進捗が出ます"]
    return "\n".join(L) + "\n"


def main() -> int:
    inv, sf, gen, rev = inventory(), facts_freshness(), generation_summary(), revenue()
    try:
        gsc = fetch_gsc()
    except Exception as e:  # noqa: BLE001
        print(f"Search Consoleの取得に失敗（続行）: {e}", file=sys.stderr)
        gsc = None
    (common.DATA_DIR / "analytics.json").write_text(
        json.dumps({"date": today_jst().isoformat(), "inventory": inv, "gsc": gsc, "generation": gen}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "weekly.md").write_text(render_report(inv, sf, gen, gsc, rev), encoding="utf-8")
    print(render_report(inv, sf, gen, gsc, rev))
    return 0


if __name__ == "__main__":
    sys.exit(main())
