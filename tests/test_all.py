"""自動運用の安全装置のテスト。実行: python -m unittest discover -s tests -v"""
import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import calc  # noqa: E402
import common  # noqa: E402
import generate_article as g  # noqa: E402
import market  # noqa: E402
import quality_gate as qg  # noqa: E402

CFG = common.load_config()


def good_body(seed: str = "A") -> str:
    parts = [f"## 見出し{i}\n\n" + "".join(f"{seed}{i}{j}は、独自の観点で検証した内容をここに記載します。数字の前提を明記し、読者が自分で確認できるようにします。" for j in range(14)) for i in range(4)]
    return "冒頭の要約です。" + "\n\n".join(parts) + "\n\n## まとめ\n\n" + "制度や条件は変更されるため、公式情報を確認してください。" * 3


def meta(**kw):
    m = {"title": "テスト用の十分な長さのタイトルです", "description": "これはテスト用のメタディスクリプションで、四十文字以上の長さを確保するための文章です。",
         "slug": "test-article", "date": dt.date.today(), "category": "seido",
         "sources": [{"title": "金融庁", "url": "https://www.fsa.go.jp/policy/nisa2/know/index.html"}]}
    m.update(kw)
    return m


class CalcTests(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(calc.years_to_fill(100_000), 15)
        self.assertEqual(calc.years_to_fill(300_000), 5)
        self.assertEqual(round(calc.future_value(30_000, 0.05, 30) / 10_000), 2497)
        self.assertEqual(calc.future_value(10_000, 0, 10), 1_200_000)

    def test_fill_plan_growth_cap(self):
        p = calc.fill_plan(2_400_000)  # つみたて120万+成長120万 -> 成長は10年で1,200万
        self.assertAlmostEqual(p["years"], 7.5)  # 2,400,000*7.5 = 1,800万
        p2 = calc.fill_plan(3_600_000)
        self.assertAlmostEqual(p2["years"], 5.0)
        self.assertTrue(calc.fill_plan(5_000_000)["capped"])

    def test_js_matches_python(self):
        js = ROOT / "static" / "js" / "tools.js"
        cases = [(30_000, 0.05, 30, 0), (100_000, 0.03, 10, 500_000), (50_000, 0.0, 20, 0), (12_345, 0.0725, 17, 100_000)]
        plans = [(600_000, 0), (2_400_000, 0), (3_600_000, 3_000_000), (1_800_000, 0), (5_000_000, 0)]
        code = ("const t=require(%r);const out={fv:%s.map(c=>t.fv(c[0],c[1],c[2],c[3])),fp:%s.map(c=>t.fillPlan(c[0],c[1]).years)};console.log(JSON.stringify(out))"
                % (str(js), json.dumps(cases), json.dumps(plans)))
        r = subprocess.run(["node", "-e", code], capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest("node が使えません: " + r.stderr[:200])
        out = json.loads(r.stdout)
        for c, v in zip(cases, out["fv"]):
            self.assertAlmostEqual(calc.future_value(c[0], c[1], c[2], c[3]), v, places=3)
        for c, v in zip(plans, out["fp"]):
            self.assertAlmostEqual(calc.fill_plan(c[0], c[1])["years"], v, places=6)

    def test_tax_merit_python_and_js(self):
        r = calc.tax_merit(30_000, 0.05, 20, 0, 0.002)
        self.assertAlmostEqual(r["tax"], r["gain"] * 0.20315)
        self.assertAlmostEqual(r["net_taxable"], r["value"] - r["tax"])
        self.assertEqual(calc.tax_merit(30_000, -0.05, 10)["tax"], 0)  # 損失なら税額0
        self.assertTrue(calc.tax_merit(100_000, 0.03, 20)["over_cap"])  # 元本2,400万円
        # 100万円の利益 -> 203,150円（記事の数値例と一致）
        self.assertAlmostEqual(1_000_000 * calc.TAX_RATE, 203_150)
        js = ROOT / "static" / "js" / "tools.js"
        cases = [(30_000, 0.05, 20, 0, 0.002), (100_000, 0.03, 10, 500_000, 0.0), (50_000, -0.02, 15, 0, 0.001)]
        code = ("const t=require(%r);console.log(JSON.stringify(%s.map(c=>{const r=t.taxMerit(c[0],c[1],c[2],c[3],c[4]);return [r.tax,r.netTaxable,r.gain]})))"
                % (str(js), json.dumps(cases)))
        res = subprocess.run(["node", "-e", code], capture_output=True, text=True)
        if res.returncode != 0:
            self.skipTest("node が使えません: " + res.stderr[:200])
        for c, v in zip(cases, json.loads(res.stdout)):
            p = calc.tax_merit(*c)
            self.assertAlmostEqual(p["tax"], v[0], places=3)
            self.assertAlmostEqual(p["net_taxable"], v[1], places=3)
            self.assertAlmostEqual(p["gain"], v[2], places=3)


class MarketTests(unittest.TestCase):
    CSV = "DATE,SP500\n2026-01-02,100\n2026-01-05,.\n2026-02-02,110\n2026-03-02,105\n2026-04-01,120\n2026-04-02,90\n"

    def test_parse_skips_missing(self):
        rows = market.parse_fred_csv(self.CSV, "SP500")
        self.assertEqual(len(rows), 5)
        self.assertNotIn("2026-01-05", [d for d, _ in rows])

    def test_stats_and_svg(self):
        rows = market.parse_fred_csv(self.CSV, "SP500")
        s = market.stats(rows)
        self.assertEqual(s["last"], 90)
        self.assertAlmostEqual(s["from_high"], (90 / 120 - 1) * 100)
        svg = market.svg_line_chart(rows, "テスト")
        self.assertIn("<path", svg)
        self.assertIn("role=\"img\"", svg)

    def test_bad_csv(self):
        with self.assertRaises(ValueError):
            market.parse_fred_csv("", "X")

    def test_chg_1d_uses_previous_row(self):
        rows = market.parse_fred_csv(self.CSV, "SP500")
        s = market.stats(rows)
        # 直前の行(2026-04-01, 120)からの変化率
        self.assertAlmostEqual(s["chg_1d"], (90 / 120 - 1) * 100)

    def test_resample_monthly_keeps_last_value_per_month(self):
        daily = [("2026-01-02", 100.0), ("2026-01-20", 105.0), ("2026-02-01", 108.0), ("2026-02-15", 111.0)]
        monthly = market.resample_monthly(daily)
        self.assertEqual(monthly, [("2026-01-01", 105.0), ("2026-02-01", 111.0)])

    def test_backtest_dca_js(self):
        """積立の疑似体験ツール（market-experience）のJS計算を、手計算と突き合わせる。"""
        js = ROOT / "static" / "js" / "tools.js"
        # 3か月分、価格 100 -> 50 -> 100 の単純な系列で、毎月1万円積み立てたケース
        rows = [["2020-01", 100], ["2020-02", 50], ["2020-03", 100]]
        code = ("const t=require(%r);console.log(JSON.stringify(t.backtestDCA(%s,'2020-01',10000)))"
                % (str(js), json.dumps(rows)))
        r = subprocess.run(["node", "-e", code], capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest("node が使えません: " + r.stderr[:200])
        out = json.loads(r.stdout)
        # 口数: 1月100円で100口 + 2月50円で200口 + 3月100円で100口 = 400口。評価額 = 400口 x 100円 = 40,000円
        self.assertAlmostEqual(out["principal"], 30000)
        self.assertAlmostEqual(out["value"], 40000)
        self.assertAlmostEqual(out["gain"], 10000)
        self.assertEqual(out["months"], 3)
        # 2月末時点: 口数100+200=300口 x 50円 = 15,000円、元本は20,000円 -> 含み損 -25%
        self.assertAlmostEqual(out["worst"], -0.25)
        self.assertEqual(out["worstYm"], "2020-02")

    def test_backtest_dca_unknown_start_returns_none(self):
        js = ROOT / "static" / "js" / "tools.js"
        code = "const t=require(%r);console.log(JSON.stringify(t.backtestDCA([['2020-01',100]],'1999-01',10000)))" % str(js)
        r = subprocess.run(["node", "-e", code], capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest("node が使えません: " + r.stderr[:200])
        self.assertEqual(json.loads(r.stdout), None)


class GateTests(unittest.TestCase):
    def check(self, m=None, body=None, others=()):
        return qg.check(m or meta(), body if body is not None else good_body(), CFG, list(others))

    def test_good_passes(self):
        self.assertEqual(self.check(), [])

    def test_banned_phrase_fails(self):
        errs = self.check(body=good_body() + "\n\nこの方法なら必ず儲かります。")
        self.assertTrue(any("禁止表現" in e for e in errs))

    def test_negated_phrase_allowed(self):
        self.assertEqual(self.check(body=good_body() + "\n\n必ず儲かるわけではありません。"), [])

    def test_unknown_affiliate_and_links(self):
        b = good_body() + "\n\n{{aff:nope}}\n\n[x](/articles/ghost/)\n\n[y](https://px.a8.net/svt/ejp?a8mat=X)\n\n[z](https://evil.example.com/)"
        errs = "\n".join(self.check(body=b))
        for w in ("未定義のアフィリエイトID", "存在しない記事", "ASPのURL", "許可されていない外部リンク"):
            self.assertIn(w, errs)

    def test_source_domain_and_count(self):
        errs = self.check(m=meta(sources=[{"title": "x", "url": "https://blog.example.com/a"}]))
        self.assertTrue(any("出典ドメイン" in e for e in errs))
        self.assertTrue(any("出典が" in e for e in self.check(m=meta(sources=[]))))

    def test_short_and_duplicate(self):
        self.assertTrue(any("短すぎ" in e for e in self.check(body="## a\n\n短い\n\n## b\n\nx\n\n## c\n\ny")))
        other = {"slug": "other", "title": "別のタイトルです十分な長さ", "body": good_body()}
        self.assertTrue(any("似すぎ" in e for e in self.check(others=[other])))

    def test_all_published_articles_pass(self):
        arts = common.load_articles(include_future=True)
        self.assertGreater(len(arts), 0)
        for a in arts:
            errs = qg.check(a, a["body"], CFG, [o for o in arts if o["slug"] != a["slug"]])
            self.assertEqual(errs, [], a["slug"])


class FakeLLM:
    def __init__(self, bodies, verdicts):
        self.bodies, self.verdicts, self.calls = list(bodies), list(verdicts), 0

    def __call__(self, system, user, max_tokens=None):
        self.calls += 1
        if "ファクトチェッカー" in system:
            return json.dumps(self.verdicts.pop(0), ensure_ascii=False)
        body = self.bodies.pop(0)
        return f"TITLE: 自動生成テスト記事のタイトルです\nDESCRIPTION: これは自動生成のテストで作られた説明文です。四十文字以上になるように十分な長さの文章を用意しています。\nFACTS: nisa_frames\n---BODY---\n{body}"


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.facts = g.load_facts()  # DATA_DIR を差し替える前に読む
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self._orig = (common.ARTICLES_DIR, common.DRAFTS_DIR, common.DATA_DIR)
        common.ARTICLES_DIR, common.DRAFTS_DIR, common.DATA_DIR = t / "articles", t / "drafts", t / "data"
        for d in (common.ARTICLES_DIR, common.DATA_DIR):
            d.mkdir()
        self.topic = {"id": "test-topic", "title_hint": "t", "keyword": "k", "category": "seido", "intent": "i",
                      "outline": ["a"], "facts": ["nisa_frames"]}

    def tearDown(self):
        common.ARTICLES_DIR, common.DRAFTS_DIR, common.DATA_DIR = self._orig
        self.tmp.cleanup()

    def test_publish_path(self):
        llm = FakeLLM([good_body("P")], [{"verdict": "pass", "unsupported": [], "risky": []}])
        r = g.generate_one(self.topic, CFG, self.facts, llm, {})
        self.assertTrue(r.startswith("PUBLISHED"), r)
        a = common.load_articles()
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["sources"][0]["url"], self.facts["nisa_frames"]["source"]["url"])  # 出典はコード側で付与
        self.assertTrue(a[0]["ai_assisted"])

    def test_retry_then_publish(self):
        bad = good_body("Q") + "\n\n絶対に儲かる方法です。"
        llm = FakeLLM([bad, good_body("R")], [{"verdict": "pass", "unsupported": [], "risky": []}])
        r = g.generate_one(self.topic, CFG, self.facts, llm, {})
        self.assertTrue(r.startswith("PUBLISHED"), r)

    def test_reject_goes_to_drafts(self):
        bad = good_body("S") + "\n\n絶対に儲かる方法です。"
        llm = FakeLLM([bad, bad], [])
        r = g.generate_one(self.topic, CFG, self.facts, llm, {})
        self.assertTrue(r.startswith("REJECTED"), r)
        self.assertEqual(common.load_articles(), [])
        self.assertTrue((common.DRAFTS_DIR / "test-topic.md").exists())

    def test_factcheck_failure_blocks(self):
        v = {"verdict": "fail", "unsupported": ["根拠のない数値"], "risky": []}
        llm = FakeLLM([good_body("T"), good_body("U")], [v, v])
        r = g.generate_one(self.topic, CFG, self.facts, llm, {})
        self.assertTrue(r.startswith("REJECTED"), r)
        self.assertEqual(common.load_articles(), [])

    def test_garbled_output_is_error_not_publish(self):
        class Bad:
            def __call__(self, *a, **k):
                return "こんにちは"
        r = g.generate_one(self.topic, CFG, self.facts, Bad(), {})
        self.assertTrue(r.startswith("ERROR"), r)
        self.assertEqual(common.load_articles(), [])

    def test_draft_mode(self):
        cfg = json.loads(json.dumps(CFG, default=str))
        cfg["generation"]["publish_mode"] = "draft"
        llm = FakeLLM([good_body("V")], [{"verdict": "pass", "unsupported": [], "risky": []}])
        r = g.generate_one(self.topic, cfg, self.facts, llm, {})
        self.assertTrue(r.startswith("DRAFT"), r)
        self.assertEqual(common.load_articles(), [])


class FactsTests(unittest.TestCase):
    def test_topics_reference_existing_facts(self):
        facts = g.load_facts()
        ids = set()
        for t in g.load_topics():
            self.assertNotIn(t["id"], ids)
            ids.add(t["id"])
            for f in t["facts"]:
                self.assertIn(f, facts, t["id"])
            self.assertIn(t["category"], {c["slug"] for c in CFG["categories"]})

    def test_facts_have_https_sources(self):
        for f in g.load_facts().values():
            self.assertTrue(f["source"]["url"].startswith("https://"))
            self.assertTrue(qg.domain_ok(f["source"]["url"], CFG["quality"]["allowed_source_domains"]), f["id"])


if __name__ == "__main__":
    unittest.main()
