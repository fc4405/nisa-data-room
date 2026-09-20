# NISAデータ室

新NISAを「一次情報と数字」で確かめる、**自動運用型の静的ブログ**です。
GitHub Pages（無料）で公開し、GitHub Actions が毎日更新します。収益はアフィリエイト（証券口座など）です。

- **はじめに読む: [SETUP.md](SETUP.md)**（最初の1回だけ必要な手作業）
- 収益の見通し・リスク: [docs/ROADMAP.md](docs/ROADMAP.md)
- ASP登録・提携申請・Search Console登録の手順: [docs/ASP_GUIDE.md](docs/ASP_GUIDE.md)

## 自動で回るもの

| いつ | 何が起きる | ファイル |
| --- | --- | --- |
| 毎朝 6:00 (JST) | 市場データ(FRED)を取得 → サイト再ビルド → 公開 | `.github/workflows/daily.yml` |
| 月・水・金 | 記事を1本自動生成 → 品質ゲート → ファクトチェック → 合格なら公開 | `scripts/generate_article.py` |
| 毎週月曜 | サイト点検・Search Console分析・収益進捗のレポート、トピック補充 | `scripts/analyze.py` |

## 安全装置

- AIが使える事実は `data/facts.yaml` のみ（出典URLはコードが付与）。
- `scripts/quality_gate.py`: 誇大表現・出典・リンク・重複・文字数を検査。不合格は公開せず `content/drafts/` へ。
- 2回目のAI呼び出しで、本文の主張が事実に裏付けられているかを検査。
- アフィリエイトリンクは `aff:ID` 記法のみ許可。自動で `rel="sponsored"` と「PR」表示。

## 手元で動かす

```bash
pip install -r requirements.txt
python -m unittest discover -s tests     # テスト
python scripts/quality_gate.py           # 全記事の品質検査
python scripts/build.py --local          # dist/ に出力
python -m http.server -d dist 8000       # http://localhost:8000
python scripts/generate_article.py --dry-run   # 次に書くトピックのプロンプトを確認（API不要）
ANTHROPIC_API_KEY=... python scripts/generate_article.py   # 実際に1本生成
```

## 構成

```
config/site.yaml         サイト設定（★を編集）
config/affiliates.yaml   アフィリエイトURL（承認後にここへ貼る）
content/articles/        公開記事（Markdown）。date が未来の記事は、その日に自動公開
content/pages/           固定ページ（運営者情報・免責など）
content/topics.yaml      記事トピックのキュー
data/facts.yaml          AIが書いてよい事実（要・定期確認）
data/market/             自動取得した市場データ
scripts/                 ビルド・生成・検査・分析
templates/ static/       デザイン・シミュレーター(JS)
```
