# 知识库检索

使用 `scripts/leafloom.py`。围绕问题提取主题和精确标识，按需补查，证据足以回答时停止。

1. 用 `search` 传 `query`、`mode:"rag"`、`top_k:3`。需要补齐截断的证据时用 `chunk`（`key` 为返回的片段 ID），核对完整原文时用 `source`（`path` 为命中的知识库相对路径）。工时经验加 `domain:"estimation"`，必要时加 `note_type:"estimation"`。已知规则存于库中且当前缺失时用 `rules`，传 `query`、`top_k:3` 和已知的 `domain`。
2. 结果不足时用 `search` 的 `mode:"wiki"`。从 `navigation.sources` 追溯原文，过期摘要只作定位。检索范围是 LeafLoom 配置的目录。
3. 需要补查已连接库中未索引的笔记时，用 `note-find`（`query`、`folder`、`limit`）定位，再用 `note-read`（`note_id` 为相对路径，支持 `offset` 和 `limit`）阅读。只查必要目录，保留当前检索范围设置。
4. 用户指定某个目录或专题集合时，只在该 `folder` 内用 `note-find` / `note-read`（或用户指出的 `.base`）操作；不要用 `search` 跨范围检索，也不要读取该目录以外的笔记。目录名、字段与组织方式以用户实际约定为准，不要假设固定预设。

优先采用适用范围内的已验证原文，保留版本、平台、验证状态及冲突。说明推断、无命中和服务故障。用 `status` 取得 `vault_root`，将确实读取的 `file_path` 拼成绝对路径并附具体笔记链接。默认给精简结论与必要来源。

只有用户要求重建索引时才使用 `reindex`，传入 `status` 返回的 `workspace_revision`。回执 `state: queued` 表示服务已经排队。
