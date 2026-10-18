# LeafLoom 0.1.3 — リリースノート

[English](../en/RELEASE_NOTES_0.1.3.md) · [简体中文](../zh-CN/RELEASE_NOTES_0.1.3.md) · [ドキュメント](../README.md)

[v0.1.2](https://github.com/DJ-Huang/LeafLoom/releases/tag/v0.1.2) 以降、Design Studio、任意の Feishu MCP と Windows/macOS の配布手順を改善しました。

## 新機能

- **Design Studio:** 複数アートボード、レイヤー、コンポーネント、レスポンシブ配置、文字・画像スタイル、アニメーション、スコープ付きスクリプトに対応。編集可能な FORMA、Motion Playground、ATELIER テンプレートを追加。編集 / プレビューを直接切り替え、ページ・選択・カメラを復元。元の HTML と分離プレビューも維持します。
- **多言語と一括出力:** 安定キーによるテキスト/画像の関連付け、英語・中国語・日本語のバリアントとレイアウト上書き。溢れ・素材・文字の事前チェック後、ページ/バリアントを PNG ZIP や複数ページ PDF に出力できます。スクリプトとモーションには HTML/ZIP 出力を使用してください。
- **編集保護:** 永続的な取り消し/やり直し、リビジョン検査、未保存変更の復元、明示的なフォルダー作成、確認付きの完全削除。
- **MCP/Feishu:** HTTP MCP はノート 23、Design Studio 14、任意の Feishu 5、計 42 ツール。Feishu は独立してインストール・認証した `lark-cli` を使用し、ノートとは別の権限が必要です。更新後にツール一覧を再取得してください。
- **開発とサイト:** 分離された任意の `--loopback-ui` ブラウザー開発入口を追加。通常のデスクトップ/MCP 既定ポート 18080 は変更しません。3 言語サイトに About と再生可能なデモ動画を追加し、OS 別に最新安定版を掲載。
- **リリース:** 対応するタグから Windows x64 / Apple Silicon macOS のインストーラーと SHA-256 を作成し、非公開の Release Draft のみ準備。公開は手動で行います。

## 互換性と注意事項

- 対応: Windows 10/11 x64、macOS 14+ Apple Silicon。正常終了後の更新でノート、設定、インデックス、モデルを保持します。
- 従来の HTML は元のファイルを残し、別の編集可能なコピーへ変換します。動的処理やスクリプトの一部は手動調整が必要です。
- PNG/PDF は静的でスクリプト・モーションを実行しません。埋め込み HTML 等にはインタラクティブ HTML を使用してください。[Design Studio の制限](../DESIGN_STUDIO.md)も参照してください。
- ブラウザー開発入口は Linux インストーラーではありません。Mac の CI 実行はパッケージ済み Windows の検証を保証しません。
- Windows は未署名、macOS は ad-hoc 署名で公証されていません。SmartScreen/Gatekeeper の警告やブロックがあり得ます。
- **添付ファイル一元化は含まれません。** [PR #18](https://github.com/DJ-Huang/LeafLoom/pull/18) は未マージです。

## 公開前の確認

v0.1.2 以降のマージ済み PR: [#10](https://github.com/DJ-Huang/LeafLoom/pull/10)、[#11](https://github.com/DJ-Huang/LeafLoom/pull/11)、[#12](https://github.com/DJ-Huang/LeafLoom/pull/12)、[#13](https://github.com/DJ-Huang/LeafLoom/pull/13)、[#14](https://github.com/DJ-Huang/LeafLoom/pull/14)、[#15](https://github.com/DJ-Huang/LeafLoom/pull/15)、[#16](https://github.com/DJ-Huang/LeafLoom/pull/16)、[#17](https://github.com/DJ-Huang/LeafLoom/pull/17)。Design Studio PR の CI は成功していますが、**0.1.3 インストーラーはタグ起点のビルドと人手による検査が必要です**。

両方のインストーラーと `SHA256SUMS.txt` を確認してください。[公開手順](../DESKTOP.md#automatic-release-drafts) · [準備チェック](../RELEASE_PREP_0.1.3.md)
