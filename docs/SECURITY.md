# Deployment and data control

[English](SECURITY.md) · [中文](#中文) · [日本語](#日本語)

**Your knowledge. Your deployment. Your control.** Run LeafLoom on your own supported computer, under your own user account. Keep your note folder wherever you choose on a local drive. The MIT license permits adapting and deploying the application subject to its terms.

The current application listens only on loopback and checks Host/Origin. Browser APIs use private sessions and CSRF checks for writes. The five legacy read-only `/mcp` tools accept unauthenticated requests from actual loopback peers; forwarded IP headers are not trusted. Legacy bearer clients retain their original scope. Full workspace tools require separate MCP-only local or Tunnel credentials and per-connection write permission (off by default). Invalid credentials never fall back to anonymous access; disabling/regenerating access revokes credentials. MCP credentials cannot authenticate browser APIs. `/ai-mcp` retains its independent session authentication. File operations enforce the connected-folder boundary and reject symbolic-link/junction traversal. HTML projects use separate same-site origins and host-only authorization. Their requests are dispatched before workspace routes and cannot reach editor APIs, MCP or the native bridge; local files remain project-scoped. See [HTML websites](HTML_PROJECTS.md).

Browsing, graphs and local retrieval do not send your notes to a hosted knowledge service. Initial dependency/model downloads need the internet. The optional CLI AI assistant can send selected content to your chosen model provider. Review references before sending and review proposed changes before saving.

These controls reduce exposure; they do not guarantee absolute security. Protect your operating-system account, keep backups and credentials private, and review untrusted files and external providers. The current desktop app does not provide a supported public multi-user web deployment. Do not expose its loopback port through a reverse proxy as if it were such a service.

Repository hygiene: use fictional paths and a public GitHub noreply address for commits. Local environment files, MCP configuration, tokens, private signing keys and note state must stay outside tracked content. Scan the worktree and full Git history with [Gitleaks](https://github.com/gitleaks/gitleaks) using `--redact=100`, then review privacy findings separately from test values. Scanning does not prove that screenshots, archives or inaccessible files are free of sensitive content. History rewriting changes commit/tag IDs; keep any recovery backup private and coordinate remote replacement separately. If a real credential was exposed, revoke/rotate it before relying on history cleanup.

## 中文

**自己的知识，自己部署，自己掌控。** 在受支持的电脑和自己的用户账户下运行 LeafLoom，自主选择本机资料目录。MIT 允许按其条款使用、修改和部署。

当前服务仅监听本机回环地址，检查 Host/Origin；网页使用私有会话，写入校验 CSRF。`/mcp` 原有五项只读工具允许实际回环连接免鉴权，不信任转发 IP 请求头；旧 bearer 客户端保持原有范围。完整笔记工具使用本机或 Tunnel 的专用 MCP 凭据，写入需单独开启且默认关闭；无效凭据不能降级为匿名访问。关闭或重新生成访问凭据立即撤销旧凭据，MCP 凭据不能调用网页管理 API。`/ai-mcp` 保留独立会话鉴权。文件操作约束在关联目录内，拒绝符号链接/junction 越界；本地 HTML 预览与编辑器写入接口隔离。

浏览、图谱和本地检索不把笔记上传到托管知识库。首次下载依赖和模型需要联网；可选 CLI AI 可能把所选内容发送给配置的模型服务。发送前检查引用，保存前检查 AI 修改。

这些机制减少暴露，无法保证绝对安全。保护系统账户、令牌和备份，审查不可信资料及外部服务。当前不是受支持的公网多用户部署方案，不应直接把本机端口代理到公网。

仓库维护使用虚构路径和 GitHub 公开 noreply 提交邮箱；环境文件、MCP 配置、令牌、私有签名密钥和笔记状态不进入版本控制。发布前用 [Gitleaks](https://github.com/gitleaks/gitleaks) 加 `--redact=100` 扫描工作区和完整历史，再区分隐私信息与测试值。扫描不能证明图片、归档或无权访问的文件没有敏感内容。重写历史会改变提交／标签标识；恢复备份应私有保存，远端替换需单独协调。若真实凭据已暴露，应先撤销／轮换，不能只依赖删除历史。

## 日本語

**自分の知識を、自分で配置し、自分で管理する。** 対応するコンピューターと自分のユーザーアカウントで実行し、ローカルの資料フォルダーを選べます。MIT の条項に従って利用、変更、配置できます。

サービスはループバックのみで待ち受け、Host/Origin を確認します。ウェブ API は非公開セッションと書き込みの CSRF 検証を使います。`/mcp` の従来の 5 つの読み取り専用ツールは実際のループバック接続を認証不要とし、転送 IP ヘッダーを信頼しません。従来の bearer 接続の範囲は維持します。完全アクセスにはローカルまたは Tunnel 専用の MCP 認証情報が必要で、書き込みは接続ごとに別途許可し、初期状態は無効です。無効な認証情報で匿名アクセスには移行しません。無効化・再生成は直ちに失効し、MCP 認証情報でウェブ管理 API は呼び出せません。`/ai-mcp` は独立したセッション認証を維持します。ファイル操作は接続フォルダー内に制限し、シンボリックリンク/junction の境界越えを拒否します。HTML プレビューは編集 API から分離します。

閲覧、グラフ、ローカル検索はメモをホスティングされた知識サービスへ送信しません。初回の依存関係とモデルのダウンロードには接続が必要です。任意の CLI AI は選択した内容を設定したモデルサービスへ送ることがあります。引用と変更を確認してください。

これらの対策はリスクを減らしますが、絶対的な安全を保証しません。OS のアカウント、トークン、バックアップを保護し、不明なファイルや外部サービスを確認してください。公開の複数ユーザー向けウェブ配置は現在サポートしていません。

リポジトリには架空のパスを使い、コミットには GitHub の公開 noreply アドレスを使用します。環境ファイル、MCP 設定、トークン、秘密署名鍵、ノート状態を追跡対象に含めないでください。公開前に [Gitleaks](https://github.com/gitleaks/gitleaks) を `--redact=100` 付きで実行し、作業ツリーと全履歴を確認してから、個人情報とテスト値を区別します。画像、アーカイブ、アクセスできないファイルまで安全と証明するものではありません。履歴の書き換えはコミット／タグ ID を変更します。復旧バックアップは非公開で保管し、リモートへの反映は別途調整してください。実際の認証情報が流出した場合は、履歴の削除だけに頼らず先に失効／更新します。
