# 工作区结构与初始化

未确认中枢位置时，采用 `status` 的 `write_targets.work_hub`（缺少时为 `工作中枢`），相对当前 LeafLoom 根：

```text
工作中枢/
  工作台.base
  配置.md        # 按需保存默认办公软件；设置页与对话共用
  数据/          # activity、project、task、import 四类记录
  来源归档/      # 按来源 ID、版本或内容散列保存文字快照
  汇报/          # 按需生成日报、周报、项目复盘、年度总结
  工作目录/      # 用户启用后按需镜像的原页面；媒体保存在附件服务器
```

## 初始化

1. `status` 定位当前根和权限；`directory-list` 检查中枢是否存在。相同管理结构直接复用；同名目录含无关内容时先说明并确定位置，不能覆盖。Skill 安装本身不会创建用户资料。
2. 用 `directory-create` 在已存在父目录中逐级创建缺失目录。用 `task-command` 创建 `工作中枢/工作台.base`，`command: {type: create, folder: 工作中枢/数据}`，保留当前 `workspace_revision` 与创建 `operation_id`。
3. 读取随 Skill 安装的 [数据库模板](../assets/workspace.base)。该文件的字段、显示名、视图、过滤条件和任务角色是初始结构。通过 `field.set`、`view.update/add/remove` 建立相同结构；每次使用最新配置版本及服务返回的视图 ID，不假设生成 ID 等于模板 ID。模板无项目预设；不要复制其他用户的项目或来源配置。
4. 数据库工具不支持模板导入且本地根确实可访问时，也可在首次创建、目标不存在的前提下使用模板创建数据库文件；应先创建数据目录，将 `leafloom.folder` 改为实际相对位置，并通过 `task-config` 和 `task-query` 验证。不能根据远端服务返回的路径假定本客户端可直接访问该主机。
5. 保持现有检索勾选。工作中枢需要直接文件/数据库查询，无需放入通用 RAG。在已有 Git 知识库且用户沿用工作资料不上传约定时，先添加精确目录忽略规则；不要自动提交或推送。新用户的同步约定不明确时，只说明当前情况，不能替其改变同步策略。

办公软件偏好独立保存在中枢的 `配置.md`，见 [办公软件配置](settings.md)。读取设置不初始化数据库；用户保存软件选择只创建所需目录和配置笔记，不生成工作事项。

## 字段约定

`record_type` 为 `activity`（工作事项）、`project`（项目档案）、`task`（任务）、`import`（采集批次）。正文保存原话、证据、个人笔记等长内容。

| 字段 | 语义 |
| --- | --- |
| record_id / record_key | 记录稳定身份 / 保存或来源去重键 |
| work_date / work_end_date / captured_at | 工作日期和结束日期 YYYY-MM-DD / 采集时间带时区 ISO 8601；单日事项起止同日，未知日期不填 |
| activity_type | progress、decision、issue、risk、plan |
| projects / candidate_projects | 确认关联项目 ID / 待补证据的额外项目 ID |
| actual_hours | 明确的实际小时数；未知不写，不能填 0 代表未知 |
| review_state | ready 或 needs_review；具体缺口写正文 |
| source_provider / source_kind / source_id / source_version / source_url | 平台或来源（如 manual、feishu、gitlab）、通用类型、带必要实例作用域的标识、版本和真实链接 |
| coverage / source_snapshot | complete、partial、unavailable、not_generated / 原文快照相对路径 |
| project_id / aliases / project_sources | 项目身份、别名和已确认来源映射（JSON 文本） |
| status / priority / due | TaskNotes 兼容任务状态、优先级和日期视图；精确截止信息保存在 external_due 中 |
| external_updated_at / external_due | 远端更新时间、平台原始截止对象 JSON 文本；JSON null 为明确无截止，字段缺失为未知 |
| assignee_ids / external_description | 负责人 ID 列表、仅对外任务描述；个人笔记留在正文 |
| sync_baseline / sync_state / pending_operation | 上次确认的字段快照、同步状态、外部写入意图与幂等键 |

数据库是文件型多选关联，不提供原生外键。项目名变更仍保留 `project_id`；AI 维护 `projects`、`candidate_projects` 两个多选字段的相同选项与 `optionMeta` 显示标签，创建/重命名项目后只更新相关选项。先建项目档案，再添加 ID 选项，最后关联事项；中断后对账补齐，不伪造或静默删除项目。

新项目来源配置使用 JSON 文本，记录 provider、kind、原始 id/url 与必要的实例/租户、读取范围及身份信息；平台特有定位字段由适配解释。已有配置原样保留、按需读取，不因格式升级重建。不要保存口令、令牌或临时下载地址；来源映射缺失时只问必要的标识，指定链接可以直接处理。

任务记录用 `tags: [task]`，其他记录不能加该标签。配置中的 `tags` 是多选元数据，TaskNotes 因而能在同一数据目录识别任务；数据库中“任务”视图过滤 `record_type=task`。任务未完成映射 `open`，完成映射 `done`；本地 `in-progress` 只是未完成任务的个人进展，不额外推导远端状态。

## 已有中枢的增量兼容

新模板只预设通用字段，source_kind 包含 manual、document、chat、meeting、task、code，并保留 feishu_doc、feishu_chat、feishu_meeting、feishu_task、gitlab 旧选项以便读取历史记录。本地手动记录可写 provider=manual、kind=manual；本地任务不填外部身份。

已有中枢先读取实际字段与视图，不重套模板。只对当前操作缺失的通用字段执行 field.set；source_kind 需新选项时合并原 options/optionMeta、保留显示名与已有选项，不替换整个配置。保留 record_id、record_key、正文、基线、自定义字段和视图；模板的 workHubVersion 仅标识新模板，不据此触发批量迁移，LeafLoom schemaVersion 仍为 1。

旧平台字段映射由相应适配负责：飞书见 [旧飞书任务兼容](feishu.md#旧飞书任务兼容)；旧 source_kind=gitlab 在明确 GitLab 采集时可提供 provider=gitlab、kind=code 的依据。只在已有记录当前需要读取/修改时补齐，采用最新配置与记录版本；冲突后重读合并，不覆盖人工内容。Skill 安装只更新指令和资源，不修改用户中枢。

## 写入和查询

`record.create` 根据视图的明确等值条件预填 `record_type`；传入 `view_id` 与显式值，创建返回路径后用 `note-read` / `note-update` 保存正文。保留返回的记录版本、配置版本、工作区版本；正文更新后旧 `record_revision` 已失效。

先按类型、项目和日期用数据库视图/`note-query` 缩小范围，再分页读取相关正文。多选项目用 `contains` 条件过滤；搜索框只查标题和元数据，不能冒充全文搜索，正文需读取或在已确认本地目录定向查找。待确认事项单独列出。报告总工时按稳定事项 ID 汇总，任务、采集批次与原文快照不重复算工作量。
