# Deployment and data control

[English](SECURITY.md) · [中文](#中文) · [日本語](#日本語)

**Your knowledge. Your deployment. Your control.** Run LeafLoom on your own supported computer, under your own user account. Keep your note folder wherever you choose on a local drive. The MIT license permits adapting and deploying the application subject to its terms.

The current application listens only on loopback, not on a public network interface. It checks Host/Origin, uses a private browser session, verifies writes with CSRF protection, and requires a bearer token for MCP. File operations enforce the connected-folder boundary and reject symbolic-link/junction traversal. Local HTML previews are isolated from the editor's write APIs.

Browsing, graphs and local retrieval do not send your notes to a hosted knowledge service. Initial dependency/model downloads need the internet. The optional CLI AI assistant can send selected content to your chosen model provider. Review references before sending and review proposed changes before saving.

These controls reduce exposure; they do not guarantee absolute security. Protect your operating-system account, keep backups and credentials private, and review untrusted files and external providers. The current desktop app does not provide a supported public multi-user web deployment. Do not expose its loopback port through a reverse proxy as if it were such a service.

## 中文

**自己的知识，自己部署，自己掌控。** 在受支持的电脑和自己的用户账户下运行 LeafLoom，自主选择本机资料目录。MIT 允许按其条款使用、修改和部署。

当前服务仅监听本机回环地址，检查 Host/Origin；网页使用私有会话，写入校验 CSRF，MCP 使用 bearer token。文件操作约束在关联目录内，拒绝符号链接/junction 越界；本地 HTML 预览与编辑器写入接口隔离。

浏览、图谱和本地检索不把笔记上传到托管知识库。首次下载依赖和模型需要联网；可选 CLI AI 可能把所选内容发送给配置的模型服务。发送前检查引用，保存前检查 AI 修改。

这些机制减少暴露，无法保证绝对安全。保护系统账户、令牌和备份，审查不可信资料及外部服务。当前不是受支持的公网多用户部署方案，不应直接把本机端口代理到公网。

## 日本語

**自分の知識を、自分で配置し、自分で管理する。** 対応するコンピューターと自分のユーザーアカウントで実行し、ローカルの資料フォルダーを選べます。MIT の条項に従って利用、変更、配置できます。

サービスはループバックのみで待ち受け、Host/Origin を確認します。ウェブは非公開セッション、書き込みは CSRF 検証、MCP は bearer token を使います。ファイル操作は接続フォルダー内に制限し、シンボリックリンク/junction の境界越えを拒否します。HTML プレビューは編集 API から分離します。

閲覧、グラフ、ローカル検索はメモをホスティングされた知識サービスへ送信しません。初回の依存関係とモデルのダウンロードには接続が必要です。任意の CLI AI は選択した内容を設定したモデルサービスへ送ることがあります。引用と変更を確認してください。

これらの対策はリスクを減らしますが、絶対的な安全を保証しません。OS のアカウント、トークン、バックアップを保護し、不明なファイルや外部サービスを確認してください。公開の複数ユーザー向けウェブ配置は現在サポートしていません。
