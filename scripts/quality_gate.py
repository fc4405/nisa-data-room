#!/usr/bin/env python3
"""公開前の品質ゲート。1つでも違反があれば「公開しない」。

  python scripts/quality_gate.py            # 公開中の全記事を検査（CIで実行）
  python scripts/quality_gate.py path.md    # 指定ファイルを検査

Googleの「スケールコンテンツの不正使用」を避け、金融情報として最低限の安全性を担保するための機械検査です。
人間の校閲の代わりではありません。
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_affiliates, load_articles, load_config, read_article, similarity, today_jst  # noqa: E402
import shortcodes  # noqa: E402

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{2,80}$")
SC_RE = re.compile(r"^\{\{(\w+):([\w\-.]+)\}\}[ \t]*$", re.M)
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
ASP_DOMAINS = ("a8.net", "px.a8.net", "afi-b.com", "moshimo.com", "accesstrade.net", "valuecommerce.com", "amzn.to")
TOOL_KEYS = {"nisa-simulator", "fee-impact", "frame-planner"}
# 「必ず儲かるわけではありません」のように、直後で打ち消している表現は誇大表現とみなさない
NEGATED = re.compile(r"^.{0,14}?(では|わけでは|とは|という意味では|ことは)(ありません|ない|限りません|言えません)")


def domain_ok(url: str, allowed: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in allowed)


def check(meta: dict, body: str, cfg: dict, others: list[dict], min_chars: int | None = None,
          require_sources: int = 1) -> list[str]:
    """違反メッセージのリストを返す（空なら合格）。others は比較対象の既存記事。"""
    errs: list[str] = []
    q = cfg["quality"]
    gen = cfg["generation"]
    min_chars = min_chars if min_chars is not None else gen["min_chars"]
    cats = {c["slug"] for c in cfg["categories"]}

    # --- メタ情報 ---
    title = str(meta.get("title", ""))
    desc = str(meta.get("description", ""))
    if not (10 <= len(title) <= 70):
        errs.append(f"titleの長さが不適切です({len(title)}文字。10〜70)")
    if not (40 <= len(desc) <= 160):
        errs.append(f"descriptionの長さが不適切です({len(desc)}文字。40〜160)")
    if not SLUG_RE.match(str(meta.get("slug", ""))):
        errs.append("slugは半角英数字とハイフンのみ(3文字以上)")
    if meta.get("category") not in cats:
        errs.append(f"未定義のカテゴリ: {meta.get('category')}")
    try:
        if meta["date"] > today_jst() + dt.timedelta(days=60):
            errs.append("dateが60日以上先です")
    except Exception:  # noqa: BLE001
        errs.append("dateが不正です")

    # --- 本文 ---
    chars = len(re.sub(r"\s+", "", body))
    if chars < min_chars:
        errs.append(f"本文が短すぎます({chars}文字 < {min_chars})")
    if re.search(r"^# [^#]", body, re.M):
        errs.append("本文にH1(#)があります。見出しは##から始めてください")
    if len(re.findall(r"^## ", body, re.M)) < 3:
        errs.append("H2見出し(##)が3つ未満です")

    # --- 禁止表現 ---
    for pat in q["banned_patterns"]:
        text = title + "\n" + body
        for m in re.finditer(pat, text):
            if NEGATED.match(text[m.end():m.end() + 30]):
                continue
            errs.append(f"禁止表現を検出: 「{m.group(0)}」")
            break

    # --- 出典 ---
    srcs = meta.get("sources") or []
    if len(srcs) < require_sources:
        errs.append(f"出典が{require_sources}件未満です")
    for s in srcs:
        u = (s or {}).get("url", "")
        if not u.startswith("https://") or not domain_ok(u, q["allowed_source_domains"]):
            errs.append(f"許可されていない出典ドメイン: {u}")

    # --- ショートコード・リンク ---
    aff = load_affiliates()
    for kind, arg in SC_RE.findall(body):
        if kind == "aff" and arg not in aff:
            errs.append(f"未定義のアフィリエイトID: {arg}")
        elif kind == "table" and arg not in shortcodes.TABLES:
            errs.append(f"未定義のtable: {arg}")
        elif kind == "tool" and arg not in TOOL_KEYS:
            errs.append(f"未定義のtool: {arg}")
        elif kind == "market":
            pass
        elif kind not in ("aff", "table", "tool", "market"):
            errs.append(f"未定義のショートコード: {kind}")
    known_slugs = {o["slug"] for o in others} | {meta.get("slug")}
    for href in LINK_RE.findall(body):
        if href.startswith("aff:"):
            if href[4:] not in aff:
                errs.append(f"未定義のアフィリエイトリンク: {href}")
        elif href.startswith("/articles/"):
            slug = href.strip("/").split("/")[-1]
            if slug not in known_slugs:
                errs.append(f"存在しない記事へのリンク: {href}")
        elif href.startswith("/tools/"):
            if href.strip("/").split("/")[-1] not in TOOL_KEYS:
                errs.append(f"存在しないツールへのリンク: {href}")
        elif href.startswith("/"):
            if href.strip("/") not in ("market", "about", "editorial-policy", "ad-policy", "disclaimer", "privacy",
                                       "articles", "tools", "changelog"):
                errs.append(f"存在しない内部リンク: {href}")
        elif href.startswith("http"):
            if any(d in href for d in ASP_DOMAINS):
                errs.append(f"ASPのURLを直接書かないでください(aff:IDを使用): {href}")
            elif not domain_ok(href, q["allowed_source_domains"]):
                errs.append(f"許可されていない外部リンク: {href}")

    # --- 重複 ---
    for o in others:
        if o["slug"] == meta.get("slug"):
            continue
        if o["title"].strip() == title.strip():
            errs.append(f"既存記事とタイトルが同一: {o['slug']}")
        sim = similarity(body, o["body"])
        if sim > gen["max_similarity"]:
            errs.append(f"既存記事と内容が似すぎています({o['slug']}: {sim:.2f} > {gen['max_similarity']})")
    return errs


def main() -> int:
    cfg = load_config()
    paths = [Path(p) for p in sys.argv[1:]]
    arts = load_articles(include_future=True)
    targets = [read_article(p) for p in paths] if paths else arts
    bad = 0
    for a in targets:
        e = check(a, a["body"], cfg, [o for o in arts if o["slug"] != a["slug"]])
        if e:
            bad += 1
            print(f"NG  {a['slug']}")
            for m in e:
                print(f"      - {m}")
        else:
            print(f"OK  {a['slug']}")
    print(f"\n{len(targets) - bad}/{len(targets)} 件が合格")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
