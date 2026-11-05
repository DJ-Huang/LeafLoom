# Work hub Skill · 工作中枢 · ワークハブ

Install **LeafLoom skill** from **Settings → Skill**. Its work hub workflow, database template and optional helpers are bundled under `~/.agents/skills/leafloom/`.

## 能力边界 / Capabilities / 機能の境界

| 能力 / Capability / 機能 | 依赖 / Dependency / 依存 |
| --- | --- |
| 工作记录、项目关联、本地任务、汇报 / Work records, projects, local tasks, reports / 作業記録・プロジェクト・ローカルタスク・レポート | LeafLoom；无需办公平台或 CLI / no office platform or CLI / オフィス製品・CLI は不要 |
| 指定资料采集与远端任务同步 / Selected source imports and remote task sync / 指定資料の取得・リモートタスク同期 | 可选飞书适配 / optional Feishu adapter / 任意の飛書連携 |
| 页面树与图片视频镜像 / Page-tree and media mirror / ページツリー・メディア同期 | 飞书、本机 LeafLoom、Python 3.11+、lark-cli 与附件服务器 / Feishu, local LeafLoom, Python, lark-cli, attachment server |
| 指定提交与 MR 采集 / Selected commits and MRs / 指定コミット・MR の取得 | 可选 GitLab 读取能力 / optional GitLab read access / 任意の GitLab 読み取り接続 |

The core is independent of office platforms and continues to use LeafLoom for storage. Platform details live in on-demand [Feishu](../leafloom/references/feishu.md) and [GitLab](../leafloom/references/gitlab.md) references. Other office platforms are not implemented yet; supplied text or exports can still be archived without pretending to access their original source. There is no connector runtime, automatic collection or new permission grant.

核心继续使用 LeafLoom 存储；平台由用户点名、链接或已确认来源配置确定。其他办公平台暂未接入，可整理提供的文字或导出文件，不默认切换到飞书。本地流程不探测办公连接。

コアの保存先は LeafLoom のままです。製品固有の手順は必要なときだけ参照します。他のオフィス製品は未対応ですが、提供されたテキスト・エクスポートは整理できます。ローカル操作でオフィス接続を確認することはありません。

## 配置办公软件 / Office preferences / オフィス製品の設定

在 **设置 → Skill → 工作中枢配置** 中勾选使用的软件，可同时选择飞书、Notion 等多个平台，逐次即时保存；也可说“同时用飞书和 Notion”“再加上 Notion”。“按来源自动选择”和“仅本地”是独立互斥模式，取消最后一个软件恢复自动选择。设置页与对话共用 `配置.md`，保留原有版本检查、历史、正文与未知选项。

Check multiple office platforms under **Settings → Skill → Work hub settings**. Automatic selection (`[auto]`) and local-only mode (`[local]`) are exclusive of platform lists. Explicit sources still take priority; selecting several platforms does not broaden collection scope or broadcast task writes. DingTalk, WeCom and Notion remain preference-only until their adapters are implemented. Old single selections are read as singleton lists without rewriting notes on read.

設定画面で利用するオフィス製品を複数チェックでき、チャットでも追加・変更できます。自動選択・ローカルのみは製品選択と排他です。旧単一選択、個人メモ、未知の設定を保持し、未連携製品の表示も維持します。

The configuration path is `<hub>/配置.md`, with `work_hub: {schema_version: 1, office_providers: [feishu, notion]}` in YAML frontmatter. The hub comes from the current vault's `write_targets.work_hub`, defaulting to `工作中枢`; adjust it under **Templates and writing → Default write locations** without moving existing data. Existing unrelated fields, comments, body text and future options are preserved. See the [configuration workflow](../leafloom/references/settings.md).

## 使用方式

在新的 Codex 聊天中输入 `$leafloom`，启用专用工作记录聊天。工作记录、本地任务与汇报无需飞书连接。以后可以直接说“今天定位了某项目的性能问题，花了两小时”“导入这篇飞书文档”“整理今天指定群的聊天和我参加的会议”“同步飞书任务”或“生成本周周报”。普通问答和其他聊天不会自动归档；只有实际写入成功后才报告已记录。

中枢默认位于当前知识库根下的 `工作中枢/`，包含 `工作台.base`、`数据/`、`来源归档/`、`汇报/`。工作事项、项目档案、任务、采集批次使用独立视图，共享 Markdown 记录。项目列为受维护的多选字段，保存稳定项目 ID；关联多个项目仍是一条事项，工时按事项 ID 去重。Skill 按项目档案和具体来源判断关联，候选项目留待补证据。工时只采用明确记录，默认周报周期为周一至周日。

周报和双周报优先参考工作中枢的 `模板/周报模板.md`；模板不存在时使用 Skill 默认结构。

飞书导入保留读取到的文字快照和整理结果，注明来源版本、时间与覆盖情况。导入日期不代表实际工作日期。文档内嵌资源、消息分页、纪要未生成和资源权限限制都需要如实保留；附件、图片、音视频原件按需补采。

“同步飞书任务”默认读取并检查差异；明确要求后才写回常用字段。外部任务按平台与来源身份匹配，原始截止时间和上次同步依据保存在通用任务字段，个人笔记保留在正文。任务记录使用 `task` 标签，兼容 TaskNotes。提取出的行动项先作候选，本地修改和远端同字段修改形成冲突时保留双方内容。重复规则等特殊字段继续在飞书管理。

## English quick start

After installation, start a new Codex chat with `$leafloom` and designate it as your work-recording chat. Describe work naturally, manage local tasks or ask for a weekly report without an office connection. Optionally provide a Feishu link, import selected chats/meetings, pull remote tasks or collect specified GitLab activity. The hub is created on first authorized use under the connected vault; installation alone does not create user notes or configure MCP.

One activity can select several projects without duplicating its hours. Project profiles and source evidence guide automatic classification; uncertain associations remain candidates. Imports retain available original text and structured outcomes with coverage limits. Weeks run Monday–Sunday, hours are actual recorded values, and historical material is referenced on demand. Task synchronization preserves local notes and detects concurrent edits; remote writes require an explicit request.

Weekly and biweekly reports use the hub's `模板/周报模板.md` when present; otherwise they use the skill's default structure.

## 日本語の使い方

インストール後、新しい Codex チャットで `$leafloom` を呼び出し、作業記録用のチャットとして使います。オフィス製品に接続せず、作業を自然に説明し、ローカルタスクや週報を管理できます。飛書文書・チャット・会議の取り込み、リモートタスク同期、指定 GitLab 活動の取得は必要時に接続します。インストール自体はメモや MCP 設定を作成しません。初回利用時に接続中の知識庫の `工作中枢/` を作成します。

一つの作業に複数プロジェクトを選択でき、工数は重複集計しません。プロジェクト情報と出典に基づいて分類し、不明な関連付けは候補として残します。原文の文字情報と整理結果、取得範囲を保存します。週報は月曜〜日曜、工数は実績のみです。飛書への書き戻しは明示的な依頼に基づき、個人メモと競合する変更を保護します。

週報・隔週報は中枢の `模板/周报模板.md` があれば参照し、なければ Skill の標準構成を使います。

## 数据与旧记录 / Data compatibility / データ互換性

- New templates use `source_provider` plus generic `source_kind` (`manual`, `document`, `chat`, `meeting`, `task`, `code`). Source IDs include instance/tenant scope where needed. Cross-platform IDs and display names are not sufficient to merge records. Existing source-kind choices and record keys remain readable.
- External tasks use `source_id`, `source_url`, `external_updated_at`, `external_description` and `external_due` (original JSON object or JSON `null`). `due` remains the TaskNotes date projection. Personal notes remain in the body, separate from external descriptions. Local tasks need no remote identity or sync metadata.
- 新模板不再预设 `feishu_*` 字段。已有中枢仅按当前操作添加缺失字段、合并选项，不重套模板或批量改写资料。飞书适配兼容读取旧字段；通用字段缺失才回退，明确空值不回退。矛盾保留双方并标记待处理，不覆盖个人笔记、记录身份或同步基线。安装 Skill 本身不升级用户数据。
- 旧飛書項目はアダプターで読み取り、必要な汎用項目のみを補います。明示的な空値は古い値で埋めず、矛盾は競合として残します。元の記録 ID・個人メモ・同期履歴・カスタムビューを保持し、一括移行は行いません。

## 飞书原页面同步 / Feishu page mirror / 飛書ページ同期

可以要求“把这个飞书页面和子页面同步到工作目录”，首次指定链接后，后续直接说“同步飞书工作记录”。默认位于 `工作中枢/工作目录/`，保留原文分组及图片视频位置，媒体上传当前附件服务器，校验成功后使用 LeafLoom 附件引用。支持超过 500 MB 的视频；普通附件、任务及其他嵌入保留来源链接。按需单向同步，不改飞书，不自动提取事项。

The installed `scripts/feishu_sync.py` uses the current user's local `lark-cli` and LeafLoom's authenticated local APIs. It requires Python 3.11+, local LeafLoom and an enabled attachment server. A first run accepts `--source <page URL>` and optional `--destination <directory>`; subsequent runs reuse the saved source for that directory. `--inventory` fetches and counts without uploading media or writing notes. Videos larger than 500 MB stream to the server; references change only after SHA-256/size verification.

Checkpoints live under `.vault-rag/work-hub-sync/`. Repeated runs reuse media receipts, discover new child pages, preserve removed source pages locally, and protect local edits/deletions using content hashes and the normal version-checked file API. Conflicting incoming text is retained as `*-incoming.json` in the checkpoint directory. Lost upload responses are reconciled with existing jobs; an ambiguous result stays pending rather than creating a duplicate. Failed transfers retain their downloads for recovery; confirmed uploads release temporary downloads. No credentials are stored in the manifest.

飛書ページと子ページを `工作中枢/工作目录/` に依頼時だけ一方向で同期できます。画像・動画は添付サーバーへの保存とハッシュ検証後に参照を置換し、500 MB を超える動画にも対応します。ローカルの編集・削除と元ページが削除された場合のコピーを保護し、中断後はチェックポイントから再開します。飛書への書き戻しや作業項目の自動作成は行いません。

## API and package contract

- `GET /api/work-hub/settings?root=<vault>` reads the shared preference without creating notes; `PUT /api/work-hub/settings` saves the nonempty `office_providers` list with `root`, `workspace_revision` and the last `revision` (empty for a missing note). Writes require the normal session/CSRF checks and reject stale file/workspace versions. Legacy `office_provider` notes and single-value requests remain readable; scalar writes are rejected once multiple platforms are configured, preventing silent loss. Multi-selection responses expose `office_provider: null` for legacy clients. No new MCP tool is needed: the Skill uses existing note tools on the same file.
- `GET /api/skills/leafloom` returns `name`, actual `path`, `installed`, and `up_to_date` across all shipped resources.
- `POST /api/skills/leafloom/install` uses the normal authenticated, CSRF-protected local installation flow; the response also includes `backup` and `backups` paths.
- Unknown skill names are rejected. Destination symlinks and non-directory parents are rejected before writes. A partial installation cannot report up to date; a later retry repairs missing resources without deleting personal files.
- The wheel includes the complete `leafloom/` bundle. The core calls the local LeafLoom API with the app's local AI permissions and uses the same version checks as other clients.
- Database records are readable independently of RAG selection. The Skill preserves the existing retrieval and sharing choices; it does not make a new directory private merely by creating it.

The offline `scripts/task_sync.py` accepts normalized `baseline`, `local`, and `remote` task objects on stdin and emits the unchanged `ok`, `pull`, `push`, `conflicts`, `agreed` and `incomplete` result fields. Omitted `schema_version` (or `1`) retains the original `{timestamp, is_all_day}` due validation. Explicit `schema_version: 2` accepts a provider-validated JSON object or null for due, compares JSON structure without platform-specific interpretation, and preserves timezone/all-day metadata. Unknown protocol versions are rejected. Snapshot fields remain `summary`, `description`, `assignees`, `due`, `status` (`todo`/`done`); absent fields are incomplete, and null due is an explicit clear. Adapters must validate and consistently project all three snapshots before comparison. No script output applies a local or remote update.

版本 2 是通用比较协议，不新增平台连接或写入能力。旧飞书输入和输出保持兼容；新平台接入需实现自己的读取、字段校验、状态映射与写回，不能仅凭通用字段或比较脚本宣称已支持。

Restart/reload the AI client if it has not discovered the newly installed Skill. Verify per-resource permissions and connectivity only when connecting those optional sources; missing access and empty results are different outcomes.
