"""データ整合性テスト: facts.yaml と topics.yaml が壊れていないか（記事自動生成の土台）"""
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import common  # noqa: E402


class FactsAndTopics(unittest.TestCase):
    def setUp(self):
        self.facts = common.load_yaml(ROOT / "data" / "facts.yaml")["facts"]
        self.topics = common.load_yaml(ROOT / "content" / "topics.yaml")["topics"]
        self.cfg = common.load_config()

    def test_fact_ids_unique_and_complete(self):
        ids = [f["id"] for f in self.facts]
        self.assertEqual(len(ids), len(set(ids)), "facts.yaml のidが重複しています")
        for f in self.facts:
            self.assertTrue(f.get("claim"), f["id"])
            self.assertTrue(f.get("verified_at"), f"{f['id']}: verified_at がありません")
            self.assertTrue(f["source"]["url"].startswith("https://"), f["id"])

    def test_fact_sources_are_allowed_domains(self):
        allowed = self.cfg["quality"]["allowed_source_domains"]
        for f in self.facts:
            host = urlparse(f["source"]["url"]).hostname or ""
            self.assertTrue(any(host == d or host.endswith("." + d) for d in allowed),
                            f"{f['id']}: 許可されていないドメイン {host}")

    def test_topics_reference_existing_facts(self):
        fact_ids = {f["id"] for f in self.facts}
        seen = set()
        for t in self.topics:
            self.assertNotIn(t["id"], seen, f"topics.yaml のidが重複: {t['id']}")
            seen.add(t["id"])
            for fid in t.get("facts", []):
                self.assertIn(fid, fact_ids, f"{t['id']} が未定義のfactを参照: {fid}")
            self.assertIn(t["category"], {c["slug"] for c in self.cfg["categories"]})


if __name__ == "__main__":
    unittest.main()
