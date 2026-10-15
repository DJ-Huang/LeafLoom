<p align="center"><img src="../../assets/brand/logo.svg" width="88" alt="LeafLoom logo" /></p>

# LeafLoom · リーフルーム

**ばらばらのメモを、知識へ。**

[English](../../README.md) · [中文](../../docs/zh-CN/README.md) · [日本語](../../docs/ja/README.md)

自分のファイルを大切にしながら、知識を活用するローカルのワークスペース。Markdown を読み書きし、根拠を検索し、アイデアのつながりを探索できます。

| 自分のファイルで | 読む、書く | 根拠を見つける | つながりを見る |
| --- | --- | --- | --- |
| ローカルの Markdown、テキスト、添付を直接使います。本文の移行は不要です。 | 閲覧を基本に、Markdown 編集、プロパティ、テンプレート、復元可能な履歴を提供します。 | キーワード、Wiki、ローカル BGE-M3 で、選択したフォルダーだけを検索します。 | 双方向リンク、バックリンク、インタラクティブな知識グラフで背景をたどれます。 |

**任意の AI.** ログイン済み CLI または HTTP MCP クライアントを接続します。AI の提案は確認してから保存します。外部サービスに送信した内容が渡ることがあります。

## つながる思考のワークスペース

初回起動時に「デモを試す」を選ぶと、内蔵の[読書と思考のスタジオ](../../vault_rag/examples/ja)を開けます。関連するメモ、ローカル HTML の読書室、プロジェクト・読書・意思決定のテンプレートを収録しています。編集内容はデモを開き直しても残ります。

### Markdown を読み、書く

表でプロジェクトを整理し、タスクリストで次の一歩を決め、リンクで思考をつなぎます。本文はローカルの Markdown ファイルです。

![表、タスク、リンク、文書の目次を備えた Markdown プロジェクトメモ](../../assets/screenshots/ja/showcase-markdown.png)

### 知識グラフでつながりをたどる

知識カード、プロジェクト、読書資料、学習ログの間にある実際のリンクを探索できます。

![読書と思考のスタジオの知識グラフ](../../assets/screenshots/ja/showcase-graph.png)

### AI Chat でメモを深める

原文と対話を並べて、回答中の参照から関連メモへ戻れます。この画面は架空のデモ対話で、外部 AI は呼び出していません。

![読書プロジェクトと参照付きの AI Chat](../../assets/screenshots/ja/showcase-ai.png)

### ローカル HTML をそのまま読む

ローカルのスタイルと図を含む HTML ガイドを、LeafLoom の中で閲覧できます。

![LeafLoom 内で表示したローカル HTML の読書室](../../assets/screenshots/ja/showcase-html.png)

## 使い始める

```sh
git clone https://github.com/DJ-Huang/LeafLoom.git
cd LeafLoom
```

1. リポジトリをダウンロードまたはクローンし、書き込み可能なフォルダーに展開します。
2. Windows 10/11 x64：`Start.cmd` をダブルクリック。 macOS 14 以降の Apple Silicon：リポジトリで `sh Start.sh` を実行。
3. 初回は専用の実行環境と依存関係を準備して画面を開きます。検索モデルは必要に応じて設定から準備します。Python、Node、Ollama の事前インストールは不要です。
4. 言語を選び、架空のデモを試すか自分のフォルダーを接続して、検索範囲を明示的に選びます。

初期状態では索引の対象は空です。まずは閲覧し、後から検索を有効にできます。

[📖 はじめてのガイドと FAQ](GUIDE.md) · [✨ AI 連携](AI.md) · [▶ 英語の紹介動画](../../assets/promo/leafloom-en.mp4)

[![英語の紹介動画](../../assets/promo/cover.png)](../../assets/promo/leafloom-en.mp4)

## 3 つの言語

ウェブ画面、ガイド、共通のデスクトップ文言は中文、English、日本語に対応します。言語設定は索引の設定とは別に保存します。

**自分の知識を、自分で配置し、自分で管理する。** 対応する端末で実行し、ローカル限定のアクセス、非公開認証、フォルダー境界で管理できます。[配置と安全性](../SECURITY.md)。

## できること・制限

メモと索引はローカルに保存します。任意の外部 AI は選択したサービスの接続・データ処理に従います。初回準備後はローカルの閲覧と検索をオフラインで使えます。

デスクトップの対応環境は上記のとおりです。クラウド同期、すべての Obsidian プラグイン、メディアの文字起こしは提供しません。

## 更新と参加

リポジトリの更新後に `Install.cmd` または `sh Install.sh` を実行してサービスを再起動します。ブラウザーの更新だけではサーバーは更新されません。

[Contributing](../../CONTRIBUTING.md) · [Changelog](../../CHANGELOG.md) · [Third-party notices](../../THIRD_PARTY_NOTICES.md) · [Media](../../docs/MEDIA.md)

MIT © 2026 DJ。依存関係とモデルはそれぞれのライセンスを保持します。 [License](../../LICENSE)

Technical compatibility: `vault-rag`, `VAULT_RAG_HOME`, `.vault-rag/`, HTTP MCP `/mcp`.
