"""共通ユーティリティ（設定読み込み・記事の読み書き）。"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = ROOT / "content" / "articles"
DRAFTS_DIR = ROOT / "content" / "drafts"
DATA_DIR = ROOT / "data"

FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)


def load_yaml(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config() -> dict:
    return load_yaml(ROOT / "config" / "site.yaml")


def load_affiliates() -> dict:
    return load_yaml(ROOT / "config" / "affiliates.yaml").get("partners", {})


def today_jst() -> dt.date:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)).date()


def split_front_matter(text: str) -> tuple[dict, str]:
    m = FM_RE.match(text)
    if not m:
        raise ValueError("front matter (--- ... ---) が見つかりません")
    meta = yaml.safe_load(m.group(1)) or {}
    return meta, m.group(2).strip() + "\n"


def to_date(v) -> dt.date:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v))


def read_article(path: Path) -> dict:
    meta, body = split_front_matter(path.read_text(encoding="utf-8"))
    meta.setdefault("slug", path.stem)
    meta.setdefault("status", "published")
    meta.setdefault("sources", [])
    meta.setdefault("tags", [])
    meta["date"] = to_date(meta["date"])
    meta["updated"] = to_date(meta.get("updated", meta["date"]))
    meta["body"] = body
    meta["path"] = path
    return meta


def load_articles(include_future: bool = False) -> list[dict]:
    """公開対象の記事を新しい順で返す。"""
    items = []
    for p in sorted(ARTICLES_DIR.glob("*.md")):
        a = read_article(p)
        if a["status"] != "published":
            continue
        if not include_future and a["date"] > today_jst():
            continue
        items.append(a)
    items.sort(key=lambda a: (a["date"], a["slug"]), reverse=True)
    return items


def dump_article(meta: dict, body: str) -> str:
    m = {k: v for k, v in meta.items() if k not in ("body", "path")}
    for k in ("date", "updated"):
        if isinstance(m.get(k), (dt.date, dt.datetime)):
            m[k] = m[k].isoformat()
    fm = yaml.safe_dump(m, allow_unicode=True, sort_keys=False, width=1000).strip()
    return f"---\n{fm}\n---\n\n{body.strip()}\n"


def char_ngrams(text: str, n: int = 3) -> set[str]:
    t = re.sub(r"\s+", "", text)
    return {t[i : i + n] for i in range(max(0, len(t) - n + 1))}


def similarity(a: str, b: str) -> float:
    A, B = char_ngrams(a), char_ngrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)
