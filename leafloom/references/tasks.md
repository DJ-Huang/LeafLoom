# 本机任务与笔记操作

下表为各操作的参数；按 [入口](../SKILL.md) 选择平台调用方式，Windows / PowerShell 使用 `scripts/leafloom.ps1 <操作> @{ 参数名 = 值 }`。任务记录沿用项目的现有数据库和视图。

| 操作 | 参数 |
|---|---|
| `status` | 无。返回连接的知识库、`workspace_revision`、写入目标和本机权限。 |
| `task-databases` | `folder?`、`limit?`、`cursor?`。列出 `.base` 数据库。 |
| `task-config` | `path`。读取视图 ID、字段、任务状态配置及数据库 `revision`。 |
| `task-query` | `path`、`view_id?`、`search?`、`limit?`、`cursor?`、`group_key?`。看板先给列摘要，再传返回的 `group_key` 分页读该列。 |
| `task-record` | `path` 为数据库、`record_path` 为记录，另可传 `offset` 和 `limit` 读正文。 |
| `task-command` | `path`、`command`、`workspace_revision`、`expected_revision`（数据库 `revision`）、`operation_id`（创建及看板操作的重试标识）。 |
| `note-read` / `note-find` | 读取 `note_id` 或以 `query` 和 `folder` 查找，支持分页。 |
| `note-create` | `path`、`workspace_revision`、`text`。 |
| `note-update` | `path`、`workspace_revision`、`expected_revision`（笔记 `revision`）。`mode` 默认为 `replace`，`replace` 或 `append` 传 `text`，`edit` 传 `edits`（`old_text` 与 `new_text`）。 |
| `directory-list` / `directory-create` | 分别为 `path?`、`limit?`、`cursor?`，或 `path`、`workspace_revision`。 |
| `note-query` | `query`（LeafLoom 查询表达式）、`limit?`、`cursor?`。 |

修改前读取最新配置和记录。新增用 `command: {"type":"record.create","title":"标题","view_id":"实际视图 ID","values":{}}`，值遵循配置中的字段和选项。更新用 `command: {"type":"record.update","path":"记录路径","record_revision":"当前记录版本","values":{}}`，只提交明确要求的字段。正文编辑先用 `note-read` 读取笔记版本；正文变更后应重新读取记录版本。创建用户要求的新任务库时用 `{"type":"create","preset":"tasks","folder":"任务目录"}`。

重试同一创建操作沿用原 `operation_id`。版本冲突后先读回并保留人工改动。对 `metadata_pending` 按服务提示稍后重读；写入结果未知时先查记录再决定是否重试。只在服务确认后报告已保存，提供实际记录路径。
