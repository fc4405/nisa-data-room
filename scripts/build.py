#!/usr/bin/env python3
"""静的サイトのビルド: content/ + data/ + templates/ -> dist/

使い方:
  python scripts/build.py            # 本番ビルド (config の base_url を使用)
  python scripts/build.py --local    # ローカル確認用 (base_url を空にする)
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import sys
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlparse

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shortcodes  # noqa: E402
from common import ROOT, load_affiliates, load_articles, load_config, split_front_matter, today_jst  # noqa: E402
from market import all_market, load_monthly_series  # noqa: E402

DIST = ROOT / "dist"
SC_LINE = re.compile(r"^\{\{(\w+):([\w\-.]+)\}\}[ \t]*$", re.M)
SC_TOKEN = re.compile(r"<p>@@(\w+):([\w\-.]+)@@</p>")
AFF_HREF = re.compile(r'href="aff:([\w\-]+)"')

TOOLS = [
    {"key": "nisa-simulator", "title": "新NISA積立シミュレーター",
     "desc": "毎月の積立額・想定年利・期間から、将来の評価額と元本、生涯投資枠の消化状況を計算します。"},
    {"key": "fee-impact", "title": "信託報酬（コスト）の差シミュレーター",
     "desc": "年間コストが異なる2つの商品を長期で比べたとき、評価額にどれだけ差が出るかを計算します。"},
    {"key": "tax-merit", "title": "新NISAの非課税メリット計算機",
     "desc": "積立の結果として、課税口座なら引かれる税金（20.315%）と、NISAで省ける金額の目安を計算します。"},
    {"key": "frame-planner", "title": "新NISA枠の使い切りプランナー",
     "desc": "毎月・ボーナス月の投資額から、年間の枠の使い方と1,800万円に届くまでの年数を確認します。"},
    {"key": "start-diagnosis", "title": "はじめかた診断｜3つの質問でわかる、あなたに合う始め方",
     "desc": "投資経験・毎月の予算・目的の3つの質問に答えると、無理のない積立額の目安と、次に読む記事・使うツールの順番をまとめて提案します。",
     "disclaimer": "これは一般的な考え方の整理であり、投資の助言ではありません。金額や配分は、ご自身の家計状況に合わせて調整してください。"},
    {"key": "market-experience", "title": "積立の疑似体験シミュレーター｜過去の指数データで確認",
     "desc": "S&P500・NASDAQ総合・日経平均の実際の指数データをもとに、「もし何年前から積み立てていたら、今いくらか」を疑似的に確認できます。",
     "disclaimer": "実際の指数データにもとづく疑似体験です。信託報酬・税金・為替（円換算）・分配金・売買コストは考慮していません。将来の運用成果を予測・保証するものではなく、特定の商品を推奨するものでもありません。"},
]


class BuildError(Exception):
    pass


class Site:
    def __init__(self, local: bool):
        self.cfg = load_config()
        self.aff = load_affiliates()
        s = self.cfg["site"]
        self.base_url = "" if local else (os.environ.get("SITE_BASE_URL") or s["base_url"]).rstrip("/")
        self.base_path = urlparse(self.base_url).path.rstrip("/") if self.base_url else ""
        self.local = local
        self.warnings: list[str] = []
        self.env = Environment(
            loader=FileSystemLoader(ROOT / "templates"),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self.env.globals.update(u=self.u, site=s, cfg=self.cfg, cats=self.cfg["categories"],
                                year=today_jst().year, tools=TOOLS, og_image=f"{self.base_url}/static/img/ogp.png")
        self.env.filters["jp_date"] = lambda d: f"{d.year}年{d.month}月{d.day}日"
        self.cat_name = {c["slug"]: c["name"] for c in self.cfg["categories"]}
        self.published: set[str] = set()
        self.scheduled: set[str] = set()

    # --- URL ---
    def u(self, path: str) -> str:
        return f"{self.base_path}{path}"

    def abs(self, path: str) -> str:
        return f"{self.base_url}{path}"

    # --- 出力 ---
    def write(self, rel: str, content: str) -> None:
        p = DIST / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def render(self, tpl: str, rel: str, **ctx) -> None:
        self.write(rel, self.env.get_template(tpl).render(**ctx))

    # --- 積立の疑似体験ツール用データ ---
    def _experience_json(self) -> str:
        """月次の長期データを、体験ツールのJS用にJSONへ（データが無い系列は空配列のまま渡す）。"""
        out: dict = {}
        for s in self.cfg["market"]["series"]:
            rows = load_monthly_series(s["id"])
            out[s["id"]] = {"name": s["name"], "unit": s["unit"], "rows": [[d[:7], v] for d, v in rows]}
        return json.dumps(out, ensure_ascii=False)

    # --- アフィリエイト ---
    def aff_link(self, pid: str) -> tuple[str, bool]:
        p = self.aff.get(pid)
        if not p:
            raise BuildError(f"未定義のアフィリエイトID: {pid}")
        url = (p.get("affiliate_url") or "").strip()
        if url:
            return url, True
        return p["official_url"], False

    def aff_cta(self, pid: str) -> tuple[str, bool]:
        p = self.aff.get(pid)
        if not p:
            raise BuildError(f"未定義のアフィリエイトID: {pid}")
        url = (p.get("affiliate_url") or "").strip()
        if not url:
            return "", False
        e = html.escape
        return (
            '<aside class="cta"><p class="cta-label">PR</p>'
            f'<p class="cta-name">{e(p["name"])}</p><p>{e(p["blurb"])}</p>'
            f'<a class="btn" href="{e(url)}" rel="sponsored nofollow noopener">{e(p["cta_text"])}</a>'
            "<p class=\"cta-note\">提供内容・条件・キャンペーンは変更されることがあります。申込前に必ず公式サイトで最新情報をご確認ください。</p></aside>",
            True,
        )

    # --- 本文レンダリング ---
    def render_body(self, body: str) -> tuple[str, list[dict], bool]:
        has_aff = False
        text = SC_LINE.sub(lambda m: f"@@{m.group(1)}:{m.group(2)}@@", body)
        md = markdown.Markdown(
            extensions=["tables", "toc", "fenced_code", "attr_list", "sane_lists"],
            extension_configs={"toc": {"toc_depth": "2-3", "permalink": False}},
        )
        out = md.convert(text)
        # 本文中の表は、スマホで横にはみ出さないようスクロール可能な枠で包む（ショートコードの表は生成時に包み済み）
        out = re.sub(r"<table>.*?</table>", lambda m: f'<div class="table-wrap table-text">{m.group(0)}</div>', out, flags=re.S)

        def block(m: re.Match) -> str:
            nonlocal has_aff
            kind, arg = m.group(1), m.group(2)
            if kind == "aff":
                h, used = self.aff_cta(arg)
                has_aff = has_aff or used
                return h
            if kind == "table":
                if arg not in shortcodes.TABLES:
                    raise BuildError(f"未定義のtable: {arg}")
                return shortcodes.TABLES[arg]()
            if kind == "market":
                return f'<figure class="chart-fig">{shortcodes.market_summary(arg)}</figure>'
            if kind == "tool":
                t = next((t for t in TOOLS if t["key"] == arg), None)
                if not t:
                    raise BuildError(f"未定義のtool: {arg}")
                return (f'<aside class="tool-callout"><p class="cta-name">{html.escape(t["title"])}</p>'
                        f'<p>{html.escape(t["desc"])}</p>'
                        f'<a class="btn btn-ghost" href="/tools/{arg}/">無料で使ってみる</a></aside>')
            raise BuildError(f"未定義のショートコード: {kind}:{arg}")

        out = SC_TOKEN.sub(block, out)
        if "@@" in out:
            raise BuildError("解決されていないショートコードがあります")

        def aff_href(m: re.Match) -> str:
            nonlocal has_aff
            url, is_aff = self.aff_link(m.group(1))
            has_aff = has_aff or is_aff
            rel = "sponsored nofollow noopener" if is_aff else "noopener"
            return f'href="{html.escape(url)}" rel="{rel}"'

        out = AFF_HREF.sub(aff_href, out)

        def art_link(m: re.Match) -> str:
            slug = m.group(1)
            if slug in self.published:
                return m.group(0)
            if slug in self.scheduled:  # 公開日前の記事へのリンクは、その日までテキストにする
                return m.group(2)
            raise BuildError(f"存在しない記事へのリンク: /articles/{slug}/")

        out = re.sub(r'<a href="/articles/([a-z0-9\-]+)/">(.*?)</a>', art_link, out)
        if self.base_path:  # サイト内リンク(/xxx/)にサブパスを付与
            out = re.sub(r'href="/(?!/)', f'href="{self.base_path}/', out)
        toc = [{"id": t["id"], "name": t["name"]} for t in md.toc_tokens]  # h2のみ目次に出す
        return out, toc, has_aff

    # --- ページ ---
    def build(self) -> None:
        if DIST.exists():
            shutil.rmtree(DIST)
        DIST.mkdir(parents=True)
        shutil.copytree(ROOT / "static", DIST / "static")

        articles = load_articles()
        self.published = {a["slug"] for a in articles}
        self.scheduled = {a["slug"] for a in load_articles(include_future=True)} - self.published
        for a in articles:
            a["html"], a["toc"], a["has_aff"] = self.render_body(a["body"])
            a["chars"] = len(re.sub(r"\s+", "", a["body"]))
            a["minutes"] = max(1, round(a["chars"] / 500))
            a["cat_name"] = self.cat_name.get(a.get("category"), "")
            a["url"] = f"/articles/{a['slug']}/"
            if a.get("category") not in self.cat_name:
                raise BuildError(f"{a['slug']}: 未定義のカテゴリ {a.get('category')}")

        market = all_market()
        market_dates = [m["stats"]["date"] for m in market if m["stats"]]
        market_asof = max(market_dates) if market_dates else None

        # 記事ページ
        for a in articles:
            related = [r for r in articles if r["slug"] != a["slug"] and r["category"] == a["category"]][:3]
            if len(related) < 3:
                related += [r for r in articles if r["slug"] != a["slug"] and r not in related][: 3 - len(related)]
            ld = {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "Article", "headline": a["title"], "description": a["description"],
                        "datePublished": a["date"].isoformat(), "dateModified": a["updated"].isoformat(),
                        "inLanguage": "ja", "mainEntityOfPage": self.abs(a["url"]),
                        "author": {"@type": "Person", "name": self.cfg["site"]["operator_name"]},
                        "publisher": {"@type": "Organization", "name": self.cfg["site"]["name"]},
                    },
                    {
                        "@type": "BreadcrumbList",
                        "itemListElement": [
                            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": self.abs("/")},
                            {"@type": "ListItem", "position": 2, "name": a["cat_name"], "item": self.abs(f"/category/{a['category']}/")},
                            {"@type": "ListItem", "position": 3, "name": a["title"], "item": self.abs(a["url"])},
                        ],
                    },
                ],
            }
            self.render("article.html", f"articles/{a['slug']}/index.html", a=a, related=related,
                        title=a["title"], description=a["description"], canonical=self.abs(a["url"]),
                        jsonld=json.dumps(ld, ensure_ascii=False), og_type="article")

        # 一覧
        self.render("list.html", "articles/index.html", heading="記事一覧", articles=articles, current=None,
                    title="記事一覧", description="新NISAの制度・口座選び・積立に関する記事の一覧です。",
                    canonical=self.abs("/articles/"))
        for c in self.cfg["categories"]:
            items = [a for a in articles if a["category"] == c["slug"]]
            if c["slug"] == "market" or items:
                self.render("list.html", f"category/{c['slug']}/index.html", heading=c["name"], articles=items,
                            current=c, title=c["name"], description=c["desc"],
                            canonical=self.abs(f"/category/{c['slug']}/"))

        # トップ
        home_ld = {
            "@context": "https://schema.org",
            "@graph": [
                {"@type": "WebSite", "name": self.cfg["site"]["name"], "url": self.abs("/"),
                 "description": self.cfg["site"]["description"], "inLanguage": "ja"},
                {"@type": "Organization", "name": self.cfg["site"]["name"], "url": self.abs("/"),
                 "logo": self.abs("/static/img/ogp.png")},
            ],
        }
        self.render("index.html", "index.html", articles=articles[:6], market=market, market_asof=market_asof,
                    title=None, description=self.cfg["site"]["description"], canonical=self.abs("/"),
                    market_table=shortcodes.market_table(), market_headline=shortcodes.market_headline(),
                    jsonld=json.dumps(home_ld, ensure_ascii=False))

        # ツール
        self.render("tools_index.html", "tools/index.html", title="無料シミュレーター一覧",
                    description="新NISAの積立・コスト・枠の使い切りを計算できる無料ツール。", canonical=self.abs("/tools/"))
        experience_json = self._experience_json()
        for t in TOOLS:
            extra = {"experience_json": experience_json} if t["key"] == "market-experience" else {}
            self.render("tool.html", f"tools/{t['key']}/index.html", t=t, title=t["title"],
                        description=t["desc"], canonical=self.abs(f"/tools/{t['key']}/"), **extra)

        # マーケット
        market_headline = shortcodes.market_headline()
        self.render("market.html", "market/index.html", market=market, market_asof=market_asof,
                    market_table=shortcodes.market_table(), market_headline=market_headline,
                    title="マーケットデータ（自動更新）",
                    description="主要株価指数と為替の最新値・騰落率・推移チャートを毎日自動更新。",
                    canonical=self.abs("/market/"))

        # 固定ページ
        for p in sorted((ROOT / "content" / "pages").glob("*.md")):
            st = self.cfg["site"]
            contacts = []
            if st.get("contact_url"):
                contacts.append(f"[お問い合わせフォーム]({st['contact_url']})")
            if st.get("contact_email"):
                contacts.append(st["contact_email"])
            contact = " / ".join(contacts) or "（連絡先は準備中です）"
            raw = p.read_text(encoding="utf-8")
            for k, v in {"site_name": st["name"], "operator_name": st["operator_name"],
                         "operator_profile": st["operator_profile"], "contact": contact}.items():
                raw = raw.replace(f"%%{k}%%", v)
            meta, body = split_front_matter(raw)
            h, toc, _ = self.render_body(body)
            self.render("page.html", f"{p.stem}/index.html", page=meta, content=h, title=meta["title"],
                        description=meta.get("description", meta["title"]), canonical=self.abs(f"/{p.stem}/"))

        # 更新履歴（自動）
        log = sorted(
            [{"date": a["updated"], "text": f"記事「{a['title']}」" + ("を公開" if a["updated"] == a["date"] else "を更新"),
              "url": a["url"]} for a in articles],
            key=lambda x: x["date"], reverse=True)
        if market_asof:
            log.insert(0, {"date": dt.date.fromisoformat(market_asof), "text": "マーケットデータを更新", "url": "/market/"})
        self.render("changelog.html", "changelog/index.html", log=log[:60], title="更新履歴",
                    description="サイトの更新履歴です。", canonical=self.abs("/changelog/"))

        self.render("404.html", "404.html", title="ページが見つかりません", description="", canonical=self.abs("/404.html"))

        # sitemap / robots / feed
        urls = ["/", "/articles/", "/tools/", "/market/", "/changelog/"]
        urls += [f"/tools/{t['key']}/" for t in TOOLS]
        urls += [f"/{p.stem}/" for p in (ROOT / "content" / "pages").glob("*.md")]
        urls += [f"/category/{c['slug']}/" for c in self.cfg["categories"] if (DIST / "category" / c["slug"]).exists()]
        lastmod = {a["url"]: a["updated"].isoformat() for a in articles}
        urls += [a["url"] for a in articles]
        sm = "".join(
            f"<url><loc>{html.escape(self.abs(u))}</loc>" + (f"<lastmod>{lastmod[u]}</lastmod>" if u in lastmod else "") + "</url>"
            for u in urls)
        self.write("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>')
        self.write("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {self.abs('/sitemap.xml')}\n")
        items = "".join(
            f"<item><title>{html.escape(a['title'])}</title><link>{html.escape(self.abs(a['url']))}</link>"
            f"<guid>{html.escape(self.abs(a['url']))}</guid>"
            f"<pubDate>{format_datetime(dt.datetime.combine(a['date'], dt.time(0), dt.timezone.utc))}</pubDate>"
            f"<description>{html.escape(a['description'])}</description></item>" for a in articles[:20])
        s = self.cfg["site"]
        self.write("feed.xml", f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{html.escape(s["name"])}</title>'
                   f'<link>{html.escape(self.abs("/"))}</link><description>{html.escape(s["description"])}</description>'
                   f"<language>ja</language>{items}</channel></rss>")
        (DIST / ".nojekyll").write_text("")

        unset = [k for k, v in self.aff.items() if not (v.get("affiliate_url") or "").strip()]
        if unset:
            self.warnings.append(f"アフィリエイトURL未設定: {', '.join(unset)}（CTAは非表示・リンクは公式サイトへ）")
        if "★" in self.cfg["site"]["operator_name"]:
            self.warnings.append("site.yaml の運営者名・プロフィールが未設定です（信頼性とASP審査に影響）")
        if "YOUR-USER" in self.base_url and not self.local:
            self.warnings.append("base_url が初期値のままです（SITE_BASE_URL か site.yaml で設定）")
        print(f"ビルド完了: 記事{len(articles)}件 -> {DIST}")
        for w in self.warnings:
            print(f"注意: {w}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true")
    args = ap.parse_args()
    try:
        Site(args.local).build()
    except BuildError as e:
        print(f"ビルドエラー: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
