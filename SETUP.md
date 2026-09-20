# セットアップ手順（最初の1回だけ・約60〜90分）

自動運用が始まったあとは、あなたの作業は「週に10分のレポート確認」だけです。
ただし、**次の作業は本人にしかできない**ため、最初に行ってください（アカウント作成・規約同意・本人確認が必要なため、代行できません）。

## 1. GitHubにサイトを置く（無料）

1. https://github.com でアカウントを作る（すでにあれば不要）。
2. 新しいリポジトリを作る（名前の例: `nisa-data-room`、公開設定は **Public**。無料プランでGitHub Pagesを使うには公開が必要です）。
3. このフォルダの中身をすべてリポジトリにアップロードする。
   - ターミナルが使えるなら:
     ```
     cd nisa-data-room
     git init -b main && git add -A && git commit -m "initial"
     git remote add origin https://github.com/<ユーザー名>/nisa-data-room.git
     git push -u origin main
     ```
   - 使えない場合: リポジトリ画面の「uploading an existing file」から、フォルダ内のファイルをドラッグ＆ドロップ（`.github` フォルダも忘れずに）。
4. リポジトリの **Settings → Pages → Build and deployment → Source** を **GitHub Actions** にする。

## 2. Claude APIキーを登録する（記事の自動生成に必要）

1. https://console.anthropic.com でAPIキーを作る。**月の利用上限（Spend limit）を必ず設定**（目安: 月$10あれば十分。1記事あたり十数円〜数十円程度）。
2. リポジトリの **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `ANTHROPIC_API_KEY` / Secret: 作成したキー
3. （キーを登録しなくても、市場データの自動更新とサイト公開は動きます。記事の自動生成だけが止まります。）

## 3. サイトの基本情報を書き換える

`config/site.yaml` の ★ 印を自分の情報に変更します。

- `operator_name` / `operator_profile`: 運営者名（ハンドルネーム可）と、投資経験・運営の目的。**実体験を具体的に書くほど信頼性とASP審査に有利**です。
- `contact_email` / `contact_url`: 公開してよい連絡先。個人のメールを出したくない場合は、Googleフォームを作ってそのURLを `contact_url: "https://..."` として `contact_email` の下の行に追加します（手順は `docs/ASP_GUIDE.md`）。ASPの審査や信頼性のため、どちらかの設定を強く推奨します。
- `base_url`: 公開URL。GitHub Pagesなら自動で判定されるため空欄のままでも動きますが、独自ドメインを使う場合は Settings → Variables に `SITE_BASE_URL` を登録してください。

## 4. 最初の公開

リポジトリの **Actions → daily-publish → Run workflow** を押します。数分でサイトが公開され、URLが表示されます
（`https://<ユーザー名>.github.io/nisa-data-room/`）。以降は毎朝6時（日本時間）に自動で更新されます。

## 5. 事実データを定期的に確認する（重要）

`data/facts.yaml` は、AIが記事に書いてよい「事実」の一覧です。**AIはここに無い制度・数値を書けません。** 収録している事実は、2026-09-20 に金融庁・国税庁・財務省・日本証券業協会の公式ページの本文と照合済みです（令和8年度税制改正の「こどもNISA」も含む）。制度は改正されるため、`verified_at` から90日を過ぎると、週次レポートが再確認を促します。再確認するときは、各 `source.url` を開いて記述が今も合っているかを見て、`verified_at` を更新してください。

## 6. Google Search Console（検索流入を増やすために必須）

1. https://search.google.com/search-console で「URLプレフィックス」としてサイトURLを追加。
2. 確認方法で「HTMLタグ」を選び、表示される `content="..."` の値を `config/site.yaml` の `google_site_verification` に貼って、コミット → 再デプロイ後に「確認」。
3. サイトマップに `sitemap.xml` を送信。
4. （任意・週次分析の自動化）サービスアカウントを作り、Search Consoleにそのメールアドレスを「制限付き」ユーザーとして追加。JSONキーを Secret `GSC_SERVICE_ACCOUNT_JSON` に、サイトのプロパティを Variable `GSC_SITE_URL`（例: `https://<ユーザー名>.github.io/nisa-data-room/`）に登録。

## 7. アフィリエイトを設定する（ここから収益）

1. ASPに登録（すべて無料）: **A8.net** / **アクセストレード** / **TGアフィリエイト** など（詳しくは `docs/ASP_GUIDE.md`）。証券口座の案件は、ASPによって提携条件・報酬が異なります。同じ案件でも報酬が違うことがあるので、管理画面で比較して選んでください。
2. **サイトが公開されてから**、SBI証券・楽天証券・マネックス証券などの案件に提携申請（審査あり。運営者情報・プライバシーポリシー等が揃っているサイトのほうが通りやすいです）。
3. 承認されたら、発行された自分用のリンクを `config/affiliates.yaml` の `affiliate_url` に貼り付けてコミット。全記事のボタンとリンクが自動で切り替わり、「PR」表示も自動で付きます。
4. **報酬額・キャンペーン内容は、記事に書かない運用**にしています（変わりやすく、古い情報が景品表示法上の問題になり得るため）。書く場合は日付つきで、手動で。

## 8. 動作確認チェックリスト

- [ ] サイトが開ける（トップ・記事・シミュレーター・マーケット）
- [ ] 運営者情報ページに自分の情報が表示されている
- [ ] Actions の実行が緑色（成功）になっている
- [ ] `data/market/` にCSVが入り、`/market/` のチャートが表示される（初回実行後）
- [ ] （APIキー設定後）Actionsを手動実行して、`content/articles/` に新しい記事が追加される、または `content/drafts/` に理由つきで退避される

---

## 運用（週10分）

- 月曜朝に `reports/weekly.md` を読む（伸びている記事・直すべき記事・下書きに退避された記事が分かります）。
- `content/drafts/` に記事があれば、冒頭のコメント（不採用の理由）を読んで、問題なければ `content/articles/` に移動して公開（`status: draft` の行を削除）。
- 月に1回、ASPの確定報酬を `data/revenue.csv` に追記（進捗が月5万円に対して何%か、レポートに出ます）。
- 制度改正があったら、`data/facts.yaml` を更新（公式URLつき）。古い記事の見直しも同時に行うと安全です。

## 止めたいとき

Actions → daily-publish → 右上「…」→ Disable workflow。記事の自動生成だけ止めたい場合は、Secret `ANTHROPIC_API_KEY` を削除するか、`config/site.yaml` の `generation.publish_mode` を `draft` にします（下書き保存のみになります）。
