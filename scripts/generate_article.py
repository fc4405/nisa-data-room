#!/usr/bin/env python3
"""記事の自動生成: topics.yaml から次のトピックを選び、Claude APIで下書き -> 品質ゲート -> LLMファクトチェック -> 公開。

  python scripts/generate_article.py                 # 1本生成（設定 articles_per_run 本）
  python scripts/generate_article.py --count 2
  python scripts/generate_article.py --topic nisa-dividend
  python scripts/generate_article.py --dry-run       # プロンプトだけ作って表示（APIは呼ばない）
  python scripts/generate_article.py --propose       # 未着手トピックが少ない時、新しいトピック案を追加

必要な環境変数: ANTHROPIC_API_KEY（--dry-run 以外）
安全設計:
  * 使ってよい事実は data/facts.yaml だけ。出典URLはコード側で付与（モデルに書かせない）。
  * 品質ゲートに落ちた記事、ファクトチェックで不支持の主張が出た記事は公開せず content/drafts/ に理由つきで保存。
  * 1トピックの失敗は最大3回まで再試行し、それ以降はスキップ（無限に課金しない）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from common import load_articles, load_config, load_yaml, today_jst  # noqa: E402
from quality_gate import check  # noqa: E402

API_URL = "https://api.anthropic.com/v1/messages"
MAX_ATTEMPTS = 3

SYSTEM_PROMPT = """あなたは日本の個人投資家向けメディア「{site}」の編集者兼ライターです。新NISAと資産形成の解説記事を書きます。

【最重要ルール】
1. 制度・数値・日付・金融機関に関する記述は、「使ってよい事実」に書かれた内容だけを根拠にする。そこに無いことは書かない（推測・記憶で補わない）。
2. 金額や利回りなどの計算結果は、本文中に自分で計算した数字を書かない。必要なら {{{{table:名前}}}} ショートコードで表を出す。
3. 特定の銘柄・ファンド・商品を「買うべき」「おすすめ」と書かない。個別の投資助言をしない。
4. 「必ず」「絶対」「確実に儲かる」「損しない」「元本保証」などの断定・誇大表現は使わない。リスク（元本割れ、損益通算不可など）を隠さない。
5. 金融機関の手数料・還元率・キャンペーン・上限額などの具体的な数値は書かない（変わりやすいため）。確認方法を書く。
6. 読者の判断を助ける実用的な内容にする。チェックリスト、判断の順序、よくある誤解、具体例など、読者が使える情報を入れる。水増しや同じ内容の言い換えをしない。
7. 文体は「です・ます」調。専門用語は初出で説明する。1文は短く。

【出力形式】（この形式以外の文字を出力しない）
TITLE: 記事タイトル（30〜60文字。検索意図に沿い、誇大にしない）
DESCRIPTION: メタディスクリプション（70〜120文字）
FACTS: 実際に使った事実のID（カンマ区切り）
---BODY---
本文（Markdown）
"""

USER_TEMPLATE = """次のトピックで記事を1本書いてください。

## トピック
- 想定タイトル案: {title_hint}
- 主なキーワード: {keyword}
- 読者の意図: {intent}
- 構成の要点:
{outline}

## 使ってよい事実（これ以外の制度・数値は書かない）
{facts}

## 使えるショートコード（本文中で単独行に書く）
- {{{{table:fill_years}}}} 毎月の投資額別・生涯枠1,800万円を使い切る年数の表
- {{{{table:fv_3}}}} / {{{{table:fv_5}}}} 年利3%/5%の仮定での積立評価額の表
- {{{{table:fee_impact}}}} 信託報酬0.1〜1.5%の30年後評価額の比較表
- {{{{table:market_table}}}} 主要指標の最新値と騰落率（自動更新）
- {{{{tool:nisa-simulator}}}} {{{{tool:fee-impact}}}} {{{{tool:frame-planner}}}} 無料シミュレーターへの案内枠
{aff_hint}

## 内部リンク候補（本文に自然に2〜4個入れる。形式: [テキスト](/articles/スラッグ/)）
{links}

{market}
## 書き方の条件
- 本文は{min_target}文字以上を目安に。H2見出し(##)を4〜7個。H1(#)は使わない。
- 冒頭で結論と、この記事で分かることを示す。最後は「まとめ」のH2で締める。
- 記事の末尾に、制度や条件は変わるため公式情報の確認を促す一文を入れる。
"""

VERIFY_PROMPT = """あなたは金融記事のファクトチェッカーです。以下の記事本文を、「使ってよい事実」と照合してください。

判定基準:
- 制度のルール・数値・日付・金融機関に関する具体的な主張で、「使ってよい事実」から直接裏付けられないものを "unsupported" に列挙する。
- {{{{table:...}}}} や {{{{tool:...}}}} などのショートコードで出る数値は、システムが計算するので問題なし。本文に書かれた数値がある場合、それが事実か、一般的な算術で自明な範囲かを確認する。
- 一般的な注意喚起（生活防衛資金を確保する等）や、読者の判断を促す助言は問題なし。
- 特定商品の推奨、断定的な収益の示唆があれば "risky" に列挙する。

出力はJSONのみ:
{{"unsupported": ["主張1", ...], "risky": ["表現1", ...], "verdict": "pass" または "fail"}}
unsupportedまたはriskyが1つでもあれば verdict は fail。

## 使ってよい事実
{facts}

## 記事本文
{body}
"""

PROPOSE_PROMPT = """新NISAの解説サイトの、次に書くべき記事トピックを{n}個提案してください。

条件:
- 「使ってよい事実」だけで正確に書ける内容に限る（事実に無い制度・数値が必要なトピックは出さない）。
- 既存記事と内容が重ならない。検索されやすい具体的な疑問（例: 「〜とは」「〜はいくら」「〜の違い」）にする。
- 特定商品の推奨につながるものは出さない。

## 使ってよい事実
{facts}

## 既存記事
{existing}

## 既に予定しているトピック
{queued}

## 直近のサイト分析（あれば）
{analytics}

出力はJSONの配列のみ。各要素: {{"id": "英小文字とハイフンのスラッグ", "title_hint": "...", "keyword": "...", "category": "seido|kouza|tsumitate|market",
"intent": "読者の疑問", "outline": ["要点1", "要点2", "要点3"], "facts": ["使う事実ID", ...]}}
"""


class LLM:
    """Anthropic Messages API への薄いクライアント（標準ライブラリのみ）。テストでは差し替える。"""

    def __init__(self, model: str, max_tokens: int):
        self.model, self.max_tokens = model, max_tokens
        self.key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.key:
            raise SystemExit("ANTHROPIC_API_KEY が設定されていません")

    def __call__(self, system: str, user: str, max_tokens: int | None = None) -> str:
        body = json.dumps({
            "model": self.model, "max_tokens": max_tokens or self.max_tokens,
            "system": system, "messages": [{"role": "user", "content": user}],
        }).encode()
        req = urllib.request.Request(API_URL, data=body, method="POST", headers={
            "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        last = None
        for i in range(4):
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    data = json.loads(r.read())
                return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}"
                if e.code not in (429, 500, 502, 503, 529):
                    break
            except Exception as e:  # noqa: BLE001
                last = str(e)
            time.sleep(5 * (i + 1) ** 2)
        raise RuntimeError(f"API呼び出しに失敗: {last}")


# --------------------------------------------------------------------------- 補助
def load_facts() -> dict[str, dict]:
    return {f["id"]: f for f in load_yaml(common.DATA_DIR / "facts.yaml")["facts"]}


def facts_text(facts: dict[str, dict], ids: list[str] | None = None) -> str:
    sel = [facts[i] for i in ids if i in facts] if ids else list(facts.values())
    return "\n".join(f"- [{f['id']}] {f['claim']}" for f in sel)


def load_topics() -> list[dict]:
    p = common.ROOT / "content" / "topics.yaml"
    return (load_yaml(p).get("topics") or []) if p.exists() else []


def state_path() -> Path:
    return common.DATA_DIR / "generation_log.json"


def load_state() -> dict:
    p = state_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_state(st: dict) -> None:
    state_path().write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def done_topic_ids() -> set[str]:
    ids = set()
    for d in (common.ARTICLES_DIR, common.DRAFTS_DIR):
        if d.exists():
            for p in d.glob("*.md"):
                try:
                    ids.add(str(common.read_article(p).get("topic_id") or p.stem))
                except Exception:  # noqa: BLE001
                    pass
    return ids


def pick_topic(topics: list[dict], state: dict, only: str | None = None) -> dict | None:
    done = done_topic_ids()
    articles = {a["slug"] for a in load_articles(include_future=True)}
    for t in topics:
        if only and t["id"] != only:
            continue
        if t["id"] in done or t["id"] in articles:
            continue
        if state.get(t["id"], {}).get("attempts", 0) >= MAX_ATTEMPTS and not only:
            continue
        return t
    return None


def market_context(needed: bool) -> str:
    if not needed:
        return ""
    from market import all_market
    rows = []
    for m in all_market():
        s = m["stats"]
        if s:
            rows.append(f"- {m['name']}: {s['last']:,.2f}（{s['date']}）1か月 {s['chg_1m'] or 0:+.1f}% / 直近1年高値から {s['from_high'] or 0:+.1f}%")
    return "## 参考: 最新の市場データ（数値を引用してよいが、売買の示唆はしない）\n" + ("\n".join(rows) or "- （データ取得待ち）") + "\n"


def build_prompts(topic: dict, cfg: dict, facts: dict) -> tuple[str, str]:
    arts = load_articles(include_future=False)
    links = "\n".join(f"- [{a['title']}](/articles/{a['slug']}/)" for a in arts[:30]) or "- （なし）"
    aff_hint = ""
    if topic.get("category") == "kouza":
        aff_hint = "- {{aff:sbi}} {{aff:rakuten}} {{aff:monex}} 証券会社の案内枠（口座選びの記事の終盤に置く。会社ごとの優劣や還元率は書かない）\n"
    ids = topic.get("facts") or list(facts.keys())
    user = USER_TEMPLATE.format(
        title_hint=topic["title_hint"], keyword=topic["keyword"], intent=topic["intent"],
        outline="\n".join(f"  - {o}" for o in topic.get("outline", [])),
        facts=facts_text(facts, ids), aff_hint=aff_hint, links=links,
        market=market_context(topic.get("needs_market", False)),
        min_target=max(2500, cfg["generation"]["min_chars"]),
    )
    return SYSTEM_PROMPT.format(site=cfg["site"]["name"]), user


def parse_output(text: str) -> tuple[dict, str]:
    text = re.sub(r"^```[a-z]*\n|\n```\s*$", "", text.strip())
    m = re.search(r"TITLE:\s*(.+)\nDESCRIPTION:\s*(.+)\nFACTS:\s*(.*)\n-{3}BODY-{3}\n(.*)\Z", text, re.S)
    if not m:
        raise ValueError("出力形式(TITLE/DESCRIPTION/FACTS/---BODY---)を解釈できません")
    return {"title": m.group(1).strip(), "description": m.group(2).strip(),
            "facts": [x.strip() for x in m.group(3).split(",") if x.strip()]}, m.group(4).strip()


def sources_for(fact_ids: list[str], facts: dict) -> list[dict]:
    seen, out = set(), []
    for i in fact_ids:
        f = facts.get(i)
        if f and f["source"]["url"] not in seen:
            seen.add(f["source"]["url"])
            out.append({"title": f["source"]["title"], "url": f["source"]["url"]})
    return out


def extract_json(text: str):
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not m:
        raise ValueError("JSONが見つかりません")
    return json.loads(m.group(1))


# --------------------------------------------------------------------------- 本体
def write_result(meta: dict, body: str, publish: bool, reasons: list[str]) -> Path:
    if publish:
        target = common.ARTICLES_DIR / f"{meta['slug']}.md"
    else:
        common.DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        target = common.DRAFTS_DIR / f"{meta['slug']}.md"
        if reasons:
            body = "<!-- 不採用の理由:\n" + "\n".join(f"- {r}" for r in reasons) + "\n-->\n\n" + body
        meta = {**meta, "status": "draft"}
    target.write_text(common.dump_article(meta, body), encoding="utf-8")
    return target


def attempt_once(topic: dict, cfg: dict, facts: dict, llm, system: str, user: str) -> tuple[dict, str, list[str]]:
    """1回分の生成と検査。(meta, body, 不合格理由のリスト) を返す。"""
    gen = cfg["generation"]
    head, body = parse_output(llm(system, user))
    used = [i for i in head["facts"] if i in facts] or [i for i in topic.get("facts", []) if i in facts]
    meta = {
        "title": head["title"], "description": head["description"], "slug": topic["id"],
        "date": today_jst(), "updated": today_jst(), "category": topic["category"],
        "tags": topic.get("tags", []), "topic_id": topic["id"], "ai_assisted": True,
        "sources": sources_for(used, facts),
    }
    reasons = check(meta, body, cfg, load_articles(include_future=True))
    if not reasons and gen.get("verify_with_llm", True):
        v = extract_json(llm("あなたは厳格なファクトチェッカーです。JSONのみを出力します。",
                             VERIFY_PROMPT.format(facts=facts_text(facts, used or None), body=body), 1500))
        if v.get("verdict") != "pass":
            reasons += [f"根拠なし: {x}" for x in v.get("unsupported", [])] + [f"危険な表現: {x}" for x in v.get("risky", [])]
            if not reasons:
                reasons.append("ファクトチェックで不合格")
    return meta, body, reasons


def generate_one(topic: dict, cfg: dict, facts: dict, llm, state: dict, tries: int = 2) -> str:
    """不合格なら理由を伝えて1回だけ書き直させる。それでもダメなら下書きに退避して公開しない。"""
    gen = cfg["generation"]
    st = state.setdefault(topic["id"], {"attempts": 0})
    st["attempts"] += 1
    st["last_try"] = today_jst().isoformat()
    system, user = build_prompts(topic, cfg, facts)
    reasons: list[str] = []
    meta, body = {}, ""
    try:
        for i in range(tries):
            u = user if not reasons else (
                user + "\n\n## 前回の原稿が不合格だった理由（必ずすべて解消して、全文を書き直すこと）\n"
                + "\n".join(f"- {r}" for r in reasons))
            meta, body, reasons = attempt_once(topic, cfg, facts, llm, system, u)
            if not reasons:
                break
    except Exception as e:  # noqa: BLE001
        st["last_result"] = f"error: {e}"
        save_state(state)
        return f"ERROR {topic['id']}: {e}"

    publish = not reasons and gen.get("publish_mode", "auto") == "auto"
    path = write_result(meta, body, publish, reasons)
    st["last_result"] = "published" if publish else ("draft" if not reasons else "rejected")
    st["reasons"] = reasons
    save_state(state)
    if publish:
        return f"PUBLISHED {topic['id']} -> {path.name}"
    return f"{'REJECTED' if reasons else 'DRAFT'} {topic['id']} -> {path.parent.name}/{path.name}" + "".join(f"\n    - {r}" for r in reasons)


def propose(cfg: dict, facts: dict, llm, n: int = 6) -> int:
    topics = load_topics()
    queued = ", ".join(t["id"] for t in topics)
    existing = "\n".join(f"- {a['slug']}: {a['title']}" for a in load_articles(include_future=True))
    ap = common.DATA_DIR / "analytics.json"
    analytics = ap.read_text(encoding="utf-8")[:2500] if ap.exists() else "（なし）"
    out = llm("あなたはSEOに詳しい編集者です。JSONのみを出力します。",
              PROPOSE_PROMPT.format(n=n, facts=facts_text(facts), existing=existing, queued=queued or "（なし）", analytics=analytics), 3000)
    new = extract_json(out)
    cats = {c["slug"] for c in cfg["categories"]}
    have = {t["id"] for t in topics} | {a["slug"] for a in load_articles(include_future=True)}
    added = 0
    for t in new:
        if not re.match(r"^[a-z0-9][a-z0-9\-]{2,80}$", t.get("id", "")) or t["id"] in have or t.get("category") not in cats:
            continue
        if not all(f in facts for f in t.get("facts", [])):
            continue
        topics.append({k: t[k] for k in ("id", "title_hint", "keyword", "category", "intent", "outline", "facts") if k in t})
        have.add(t["id"])
        added += 1
    import yaml
    (common.ROOT / "content" / "topics.yaml").write_text(
        "# 記事トピックのキュー。上から順に自動で消化されます（--propose で自動追加もされます）。\n"
        + yaml.safe_dump({"topics": topics}, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    return added


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int)
    ap.add_argument("--topic")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--propose", action="store_true")
    args = ap.parse_args()
    cfg, facts = load_config(), load_facts()
    gen = cfg["generation"]

    if args.dry_run:
        topics = load_topics()
        t = pick_topic(topics, load_state(), args.topic)
        if not t:
            print("未着手のトピックがありません")
            return 0
        s, u = build_prompts(t, cfg, facts)
        print(f"[dry-run] topic={t['id']} system={len(s)}字 user={len(u)}字\n\n{u}")
        return 0

    llm = LLM(gen["model"], gen["max_tokens"])
    if args.propose:
        print(f"{propose(cfg, facts, llm)} 件のトピックを追加しました")
        return 0

    state, topics = load_state(), load_topics()
    # 未着手トピックが少なくなったら自動補充
    pending = [t for t in topics if t["id"] not in done_topic_ids()]
    if len(pending) < 3:
        try:
            print(f"トピック補充: {propose(cfg, facts, llm)} 件追加")
            topics = load_topics()
        except Exception as e:  # noqa: BLE001
            print(f"トピック補充に失敗（続行）: {e}", file=sys.stderr)

    n = args.count or gen.get("articles_per_run", 1)
    made = 0
    for _ in range(n):
        t = pick_topic(topics, state, args.topic)
        if not t:
            print("未着手のトピックがありません")
            break
        r = generate_one(t, cfg, facts, llm, state)
        print(r)
        made += r.startswith("PUBLISHED")
        if args.topic:
            break
    print(f"公開: {made} 本")
    return 0


if __name__ == "__main__":
    sys.exit(main())
