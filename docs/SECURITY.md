# Deployment and data control

The general file tools share the existing workspace grants: `vault_files` reads metadata/original bytes and prepares private ZIP caches; `vault_files_update` uploads and manages attachments with the separate write grant. Every request binds a workspace revision, and byte reads also require the file revision. Host-provided file URLs are downloaded over HTTPS with public-address validation and DNS pinning on every redirect; ambient proxy, cookie and bearer credentials are never forwarded. Upload staging is private to a credential generation and expires after 24 hours. Publishing rechecks authorization and preserves duplicate names; receipts support idempotent retries. Attachment moves/trash require a versioned preview and retain recoverable journals; background workers recheck live grants at safe boundaries. Browser recovery uses its own authenticated action. These tools do not grant arbitrary local-path access or expand RAG scope.

Persistent asset delivery is an explicit write operation restricted to originals in the current attachment catalog. Only the authenticated management UI selects its fixed destination directory; MCP cannot supply arbitrary destination paths. Credential-scoped task records recheck write access before publication and return paths only for completed output copies, with the service host's device identity. These outputs survive cache cleanup and must be managed separately by the user. Private download staging paths and NAS credentials remain undisclosed. Metadata-only asset vectors reuse the local worker without adding asset contents to note RAG. See [asset workflows](ASSET_WORKFLOWS.md).

[English](SECURITY.md) · [中文](#中文) · [日本語](#日本語)

**Your knowledge. Your deployment. Your control.** Run LeafLoom on your own supported computer, under your own user account. Keep your note folder wherever you choose on a local drive. The MIT license permits adapting and deploying the application subject to its terms.

The current application listens only on loopback and checks Host/Origin. Browser APIs use private sessions and CSRF checks for writes. The five legacy read-only `/mcp` tools accept unauthenticated requests from actual loopback peers; forwarded IP headers are not trusted. Legacy bearer clients retain their original scope. Full workspace tools require separate MCP-only local or Tunnel credentials and per-connection write permission (off by default). Invalid credentials never fall back to anonymous access; disabling all resource scopes or regenerating credentials revokes them. MCP credentials cannot authenticate browser APIs. `/ai-mcp` retains its independent session authentication. File operations enforce the connected-folder boundary and reject symbolic-link/junction traversal. HTML projects use separate same-site origins and host-only authorization. Their requests are dispatched before workspace routes and cannot reach editor APIs, MCP or the native bridge; local files remain project-scoped. See [HTML websites](HTML_PROJECTS.md).

Browsing, graphs and local retrieval do not send your notes to a hosted knowledge service. Initial dependency/model downloads need the internet. The optional CLI AI assistant can send selected content to your chosen model provider. Review references before sending and review proposed changes before saving.

Optional [Feishu integration](FEISHU.md) invokes your externally configured native lark-cli.
The CLI owns login credentials; LeafLoom stores only settings and allowlisted account
verification results. Feishu operations contact the cloud and return requested results
to the calling AI client. Local/Tunnel Feishu permissions default off and are independent
of notes. A dedicated MCP credential stays active while any of its resource scopes is
enabled; disabling a scope blocks that resource, and disabling all scopes or rotating
the credential revokes it entirely. Legacy clients have no Feishu privileges.

These controls reduce exposure; they do not guarantee absolute security. Protect your operating-system account, keep backups and credentials private, and review untrusted files and external providers. The current desktop app does not provide a supported public multi-user web deployment. Do not expose its loopback port through a reverse proxy as if it were such a service.

The owned Tunnel uses a separate `X-LeafLoom-Tunnel-Authorization` runtime proof, checked only for actual loopback MCP requests against the current in-memory secret. Connector `Authorization` headers do not select a different identity when this proof is valid. Invalid/revoked proofs fail closed; resource and write permissions are still checked at execution. This header grants no browser/API authentication and is not a trusted forwarded-IP marker.

Repository hygiene: use fictional paths and a public GitHub noreply address for commits. Local environment files, MCP configuration, tokens, private signing keys and note state must stay outside tracked content. Scan the worktree and full Git history with [Gitleaks](https://github.com/gitleaks/gitleaks) using `--redact=100`, then review privacy findings separately from test values. Scanning does not prove that screenshots, archives or inaccessible files are free of sensitive content. History rewriting changes commit/tag IDs; keep any recovery backup private and coordinate remote replacement separately. If a real credential was exposed, revoke/rotate it before relying on history cleanup.

## 中文

**自己的知识，自己部署，自己掌控。** 在受支持的电脑和自己的用户账户下运行 LeafLoom，自主选择本机资料目录。MIT 允许按其条款使用、修改和部署。

当前服务仅监听本机回环地址，检查 Host/Origin；网页使用私有会话，写入校验 CSRF。`/mcp` 原有五项只读工具允许实际回环连接免鉴权，不信任转发 IP 请求头；旧 bearer 客户端保持原有范围。完整笔记工具使用本机或 Tunnel 的专用 MCP 凭据，写入需单独开启且默认关闭；无效凭据不能降级为匿名访问。关闭全部资源权限或重新生成访问凭据立即撤销旧凭据，MCP 凭据不能调用网页管理 API。`/ai-mcp` 保留独立会话鉴权。文件操作约束在关联目录内，拒绝符号链接/junction 越界；本地 HTML 预览与编辑器写入接口隔离。

浏览、图谱和本地检索不把笔记上传到托管知识库。首次下载依赖和模型需要联网；可选 CLI AI 可能把所选内容发送给配置的模型服务。发送前检查引用，保存前检查 AI 修改。

可选[飞书接入](FEISHU.md)调用自行配置的原生 lark-cli，由 CLI 管理登录凭据；LeafLoom 仅保存设置与白名单内的验证信息。云端操作向调用的 AI 返回所需结果。本机／Tunnel 的飞书权限默认关闭，与笔记权限独立。专用凭据只要仍有资源权限便保持有效；关闭某项权限立即阻止该资源操作，关闭全部资源权限或重新生成凭据才整体失效。旧客户端没有飞书权限。

这些机制减少暴露，无法保证绝对安全。保护系统账户、令牌和备份，审查不可信资料及外部服务。当前不是受支持的公网多用户部署方案，不应直接把本机端口代理到公网。

仓库维护使用虚构路径和 GitHub 公开 noreply 提交邮箱；环境文件、MCP 配置、令牌、私有签名密钥和笔记状态不进入版本控制。发布前用 [Gitleaks](https://github.com/gitleaks/gitleaks) 加 `--redact=100` 扫描工作区和完整历史，再区分隐私信息与测试值。扫描不能证明图片、归档或无权访问的文件没有敏感内容。重写历史会改变提交／标签标识；恢复备份应私有保存，远端替换需单独协调。若真实凭据已暴露，应先撤销／轮换，不能只依赖删除历史。

## 日本語

**自分の知識を、自分で配置し、自分で管理する。** 対応するコンピューターと自分のユーザーアカウントで実行し、ローカルの資料フォルダーを選べます。MIT の条項に従って利用、変更、配置できます。

サービスはループバックのみで待ち受け、Host/Origin を確認します。ウェブ API は非公開セッションと書き込みの CSRF 検証を使います。`/mcp` の従来の 5 つの読み取り専用ツールは実際のループバック接続を認証不要とし、転送 IP ヘッダーを信頼しません。従来の bearer 接続の範囲は維持します。完全アクセスにはローカルまたは Tunnel 専用の MCP 認証情報が必要で、書き込みは接続ごとに別途許可し、初期状態は無効です。無効な認証情報で匿名アクセスには移行しません。全リソース権限の無効化・認証情報の再生成は直ちに失効し、MCP 認証情報でウェブ管理 API は呼び出せません。`/ai-mcp` は独立したセッション認証を維持します。ファイル操作は接続フォルダー内に制限し、シンボリックリンク/junction の境界越えを拒否します。HTML プレビューは編集 API から分離します。

閲覧、グラフ、ローカル検索はメモをホスティングされた知識サービスへ送信しません。初回の依存関係とモデルのダウンロードには接続が必要です。任意の CLI AI は選択した内容を設定したモデルサービスへ送ることがあります。引用と変更を確認してください。

任意の [Feishu 連携](FEISHU.md)は、外部で設定したネイティブ lark-cli を呼び出します。認証情報は CLI が管理し、LeafLoom は設定と許可された検証情報のみを保存します。クラウドの結果は呼び出し元 AI に返されます。ローカル／Tunnel の Feishu 権限は初期状態で無効で、ノート権限とは独立しています。専用認証情報は何らかのリソース権限がある間は有効です。各権限の無効化は対象への操作を拒否し、全権限の無効化または再生成で認証情報全体を失効させます。従来の接続に Feishu 権限はありません。

これらの対策はリスクを減らしますが、絶対的な安全を保証しません。OS のアカウント、トークン、バックアップを保護し、不明なファイルや外部サービスを確認してください。公開の複数ユーザー向けウェブ配置は現在サポートしていません。

リポジトリには架空のパスを使い、コミットには GitHub の公開 noreply アドレスを使用します。環境ファイル、MCP 設定、トークン、秘密署名鍵、ノート状態を追跡対象に含めないでください。公開前に [Gitleaks](https://github.com/gitleaks/gitleaks) を `--redact=100` 付きで実行し、作業ツリーと全履歴を確認してから、個人情報とテスト値を区別します。画像、アーカイブ、アクセスできないファイルまで安全と証明するものではありません。履歴の書き換えはコミット／タグ ID を変更します。復旧バックアップは非公開で保管し、リモートへの反映は別途調整してください。実際の認証情報が流出した場合は、履歴の削除だけに頼らず先に失効／更新します。

### Static design publication

A publication is a bounded snapshot of a saved design and its registered assets,
not permission to crawl project folders or fetch external URLs. Desktop IPC accepts
a job identifier only and is restricted to the trusted application's main frame.
The temporary export window has sandbox/context isolation enabled, Node disabled,
no preload, denied permissions and downloads, and a nonpersistent resource-only
session. CSP disables authored script, objects, forms, connections and frames;
only the application's trusted static renderer is executed by the main process.
The optional headless renderer likewise intercepts requests and fails closed.
Missing or blocked assets produce explicit item errors rather than enabling wider
network/file access. Existing interactive project isolation is unchanged.

Publication snapshots/results have finite per-job and session memory budgets.
They are transient service-session work; after a restart, start a new publication.
The source document and its undo history remain durable. Native output intake
checks type and requested dimensions, and never treats an upload as executable
code. The standard API authentication, CSRF and connected-folder checks still apply.
