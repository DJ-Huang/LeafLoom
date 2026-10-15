# Agent 工作约定

## 核心架构

- `vault_rag/`：Python 本地服务，提供文件 API、HTTP MCP、目录与检索；模型和向量任务由 `rag_process` 独立进程处理。
- `web/`：共享 React 前端；Markdown 正文使用 Tiptap/ProseMirror，源码使用 CodeMirror，共用文档状态与撤销历史。
- `desktop/`：Electron 加载同一前端，只负责窗口、托盘和系统集成。HTML 项目以独立来源运行，与管理界面隔离。
- 笔记保存在用户目录，索引、历史和回收区在其 `.vault-rag/`。浏览范围与检索范围独立，检索只使用明确选择的内容。

## 修改与交付

- 以当前源码和局部指令为准，保持改动聚焦，保留无关修改；保护用户原文件、草稿、版本校验和访问边界。
- **功能完成时同步补齐文档**：操作变化更新三语使用指南，用户可见变化更新三语更新记录；入口、架构或配置变化更新对应说明，必要时调整三语首页。
- 文档入口为 `docs/README.md`，指南为 `docs/{en,zh-CN,ja}/GUIDE.md`；新增文档要加入目录。架构细节见 `docs/ARCHITECTURE.md`，开发约定见 `CONTRIBUTING.md`。
- 界面文案维护 `vault_rag/locales/messages.tsv`，用 `scripts/compile_locales.py` 生成语言文件；构建产物不作为源码维护。
- 按改动运行最小必要检查；纯文档检查链接与差异即可。交付说明改了什么、验证了什么，未执行的验证不声称通过。
