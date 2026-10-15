# Deployment and data control

[English](SECURITY.md) · [中文](#中文) · [日本語](#日本語)

**Your knowledge. Your deployment. Your control.** Run LeafLoom on your own supported computer, under your own user account. Keep your note folder wherever you choose on a local drive. The MIT license permits adapting and deploying the application subject to its terms.

The current application listens only on loopback and checks Host/Origin. Browser APIs use private sessions and CSRF checks for writes. The read-only knowledge `/mcp` accepts unauthenticated requests from actual loopback peers; forwarded IP headers are not trusted. Existing bearer-token clients remain compatible. `/ai-mcp` retains its independent session authentication. File operations enforce the connected-folder boundary and reject symbolic-link/junction traversal. HTML projects use separate same-site origins and host-only authorization. Their requests are dispatched before workspace routes and cannot reach editor APIs, MCP or the native bridge; local files remain project-scoped. See [HTML websites](HTML_PROJECTS.md).

Browsing, graphs and local retrieval do not send your notes to a hosted knowledge service. Initial dependency/model downloads need the internet. The optional CLI AI assistant can send selected content to your chosen model provider. Review references before sending and review proposed changes before saving.

These controls reduce exposure; they do not guarantee absolute security. Protect your operating-system account, keep backups and credentials private, and review untrusted files and external providers. The current desktop app does not provide a supported public multi-user web deployment. Do not expose its loopback port through a reverse proxy as if it were such a service.

## 中文

**自己的知识，自己部署，自己掌控。** 在受支持的电脑和自己的用户账户下运行 LeafLoom，自主选择本机资料目录。MIT 允许按其条款使用、修改和部署。

当前服务仅监听本机回环地址，检查 Host/Origin；网页使用私有会话，写入校验 CSRF。只读知识库 `/mcp` 允许实际回环连接免鉴权，不信任转发 IP 请求头；已有 bearer token 客户端仍兼容。`/ai-mcp` 保留独立会话鉴权。文件操作约束在关联目录内，拒绝符号链接/junction 越界；本地 HTML 预览与编辑器写入接口隔离。

浏览、图谱和本地检索不把笔记上传到托管知识库。首次下载依赖和模型需要联网；可选 CLI AI 可能把所选内容发送给配置的模型服务。发送前检查引用，保存前检查 AI 修改。

这些机制减少暴露，无法保证绝对安全。保护系统账户、令牌和备份，审查不可信资料及外部服务。当前不是受支持的公网多用户部署方案，不应直接把本机端口代理到公网。

## 日本語

**自分の知識を、自分で配置し、自分で管理する。** 対応するコンピューターと自分のユーザーアカウントで実行し、ローカルの資料フォルダーを選べます。MIT の条項に従って利用、変更、配置できます。

サービスはループバックのみで待ち受け、Host/Origin を確認します。ウェブ API は非公開セッションと書き込みの CSRF 検証を使います。読み取り専用の `/mcp` は実際のループバック接続を認証不要とし、転送 IP ヘッダーを信頼しません。既存の bearer token も引き続き利用できます。`/ai-mcp` は独立したセッション認証を維持します。ファイル操作は接続フォルダー内に制限し、シンボリックリンク/junction の境界越えを拒否します。HTML プレビューは編集 API から分離します。

閲覧、グラフ、ローカル検索はメモをホスティングされた知識サービスへ送信しません。初回の依存関係とモデルのダウンロードには接続が必要です。任意の CLI AI は選択した内容を設定したモデルサービスへ送ることがあります。引用と変更を確認してください。

これらの対策はリスクを減らしますが、絶対的な安全を保証しません。OS のアカウント、トークン、バックアップを保護し、不明なファイルや外部サービスを確認してください。公開の複数ユーザー向けウェブ配置は現在サポートしていません。
