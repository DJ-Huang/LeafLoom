# LeafLoom に参加する

[English](../../CONTRIBUTING.md) · [中文](../zh-CN/COMMUNITY.md) · [日本語](COMMUNITY.md)

問題、期待する動作、環境・バージョン、再現手順を記載してください。架空のメモを使い、パス、ユーザー名、トークン、実際の会話を除いてください。セキュリティ問題は GitHub の非公開報告を優先し、認証情報や個人の資料を公開しないでください。

変更は目的に絞り、無関係な作業を保持します。`vault-rag`、`VAULT_RAG_HOME`、`.vault-rag` は互換性のための識別子です。文言は `vault_rag/locales/messages.tsv` で 3 言語とプレースホルダーを更新し、`python scripts/compile_locales.py` を実行します。生成した JSON やビルド結果を直接編集しないでください。

Python 3.12 とロックした依存関係を使い、`web/` で `npm ci`、`npm run build` を実行します。変更に関係する確認を行い、製品化の回帰は `tests/test_productization.py` を参照してください。画面の検証には独立した架空の知識庫を使い、実行した検証と未確認の環境を明記します。[メディア制作](../MEDIA.md) も参照してください。貢献は MIT、第三者の素材は元のライセンスを保持します。
