# LeafLoom v0.1.3 发布准备与 PR 核对

> 整理日期：2026-10-18（Asia/Singapore） · 状态：**Release 分支准备中，未创建 v0.1.3 Tag、未发布 Release**。

## 范围和基线

- 仓库：[DJ-Huang/LeafLoom](https://github.com/DJ-Huang/LeafLoom)；上一个正式版：[v0.1.2](https://github.com/DJ-Huang/LeafLoom/releases/tag/v0.1.2)，2026-10-16 发布，Tag 对应 `333abb84`。
- 已核对的基线：`v0.1.2...main` 共有 **50 个提交**（包含合并提交及直接提交）；`main` 基线为 `42b5730`（合并 PR #17）。
- 本次发布分支：[`release/v0.1.3`](https://github.com/DJ-Huang/LeafLoom/tree/release/v0.1.3)，从上述 `main` 创建，不自动包含其他开放 PR。
- 本次发布说明：[English](en/RELEASE_NOTES_0.1.3.md) · [简体中文](zh-CN/RELEASE_NOTES_0.1.3.md) · [日本語](ja/RELEASE_NOTES_0.1.3.md)。

## 上次发布之后已合并的 PR

| PR | 审核范围 | 风险与必要复核 |
| --- | --- | --- |
| [#10](https://github.com/DJ-Huang/LeafLoom/pull/10) | 官网 Release Pages 权限及各系统安装包保留 | 复核新 Release 在官网 Windows/Mac 上的下载版本与摘要 |
| [#11](https://github.com/DJ-Huang/LeafLoom/pull/11) | Feishu MCP 工具、权限及凭据边界 | 原 PR 未执行完整测试；在具备完整依赖的环境复核授权、读写、撤销与 CLI 可用性 |
| [#12](https://github.com/DJ-Huang/LeafLoom/pull/12) | 三语言 About 页面 | 检查三语路径、外链、页面构建 |
| [#13](https://github.com/DJ-Huang/LeafLoom/pull/13) | 「Skill」设置入口重命名 | 检查三语言文案和导航 |
| [#14](https://github.com/DJ-Huang/LeafLoom/pull/14) | 双平台自动构建、校验和未公开 Release Draft | 必须有对应版本的 Tag；确认两端安装包、SHA-256 与草稿保护 |
| [#15](https://github.com/DJ-Huang/LeafLoom/pull/15) | 可选 localhost 浏览器开发入口 | 常规安装版及 MCP 端口 18080 不变；继续确认隔离状态目录和鉴权 |
| [#16](https://github.com/DJ-Huang/LeafLoom/pull/16) | 官网演示视频播放 | 在三个语言路径验证视频、直达链接和下载功能 |
| [#17](https://github.com/DJ-Huang/LeafLoom/pull/17) | Design Studio 编辑、模板、变体、静态发布及安全边界 | 重点回归历史恢复、HTML 动态隔离、多语言字体、PNG/PDF、原始项目保护 |

**未纳入：** [PR #18](https://github.com/DJ-Huang/LeafLoom/pull/18) 附件索引与迁移仍为 Open，不属于已合并代码。不得在 v0.1.3 Release Notes 宣称已支持附件集中迁移，也不要因发布准备自动合并该 PR。

## 已有证据和本次本机检查

| 项目 | 结果 / 边界 |
| --- | --- |
| PR #17 最终 Design Studio 工作流 | [CI 39122535081](https://github.com/DJ-Huang/LeafLoom/actions/runs/39122535081) 成功；原 PR 记录完整浏览器和 macOS 原生发布验证 |
| PR #17 HTML 兼容工作流 | [CI 39122535041](https://github.com/DJ-Huang/LeafLoom/actions/runs/39122535041) 成功 |
| PR #17 官网工作流 | [CI 39122535063](https://github.com/DJ-Huang/LeafLoom/actions/runs/39122535063) 成功；[合并后的官网构建](https://github.com/DJ-Huang/LeafLoom/actions/runs/39123342773) 成功 |
| 源码版本一致性 | `python3 scripts/desktop_release.py check`：**0.1.3 一致**，包括 Python、前端/桌面清单及锁文件 |
| 发布草稿回归 | `tests/test_desktop_release.py` **16 项通过**，含人工说明、自动变更列表、校验值及草稿保护 |
| 官网构建逻辑 | `tests/test_site.py` **6 项通过** |
| 依赖锁检查 | `uv lock --check --offline` 通过 |
| 本机额外集成测试 | 隔离检出未安装完整 Python 项目依赖：缺 `frontmatter`、`fastapi`、`starlette`，Feishu/Tunnel/Design Studio/浏览器开发测试在导入阶段停止；**不等同于功能失败或测试通过**。须在完整锁定环境/CI 运行 |
| 双平台 v0.1.3 安装包 | **尚未构建或验收**；原 PR 的验证不能替代新版本二进制验证 |

## 发布风险及放行条件

1. **先合并发布分支进 `main`，再从确认后的发布提交创建 `v0.1.3` Tag。** 官网 Release 触发的构建可能读取当前 `main`；避免 Tag 代码与官网源代码不一致。
2. 在发布分支手动触发 [LeafLoom desktop packages](../.github/workflows/desktop.yml)（`workflow_dispatch`）检查 Windows 及 macOS；该模式仅产出 CI Artifacts，不生成 Release。Design Studio、Feishu/Tunnel、浏览器开发相关回归应在完整依赖环境完成。
3. 审核 `docs/en/RELEASE_NOTES_0.1.3.md` 等三语言说明；草稿生成脚本把英文人工说明放在 GitHub 自动生成的更改列表之前，重新运行时保留已人工编辑的草稿正文。
4. 仅在合并后推送**新建且与版本一致**的 `v0.1.3` Tag；观察 `desktop.yml` 的 validate、Windows、macOS 与 release-draft 全部通过。
5. 草稿必须包含 `LeafLoom-0.1.3-windows-x64-setup.exe`、`LeafLoom-0.1.3-macos-arm64.dmg` 和 `SHA256SUMS.txt`；检查实际下载、SHA-256、升级保留数据、常用编辑及 MCP。发布前进行凭据/敏感信息扫描。
6. 两平台分别验证：Windows 未签名、Mac 临时签名且未公证，可能遇到系统安全拦截；Mac CI 不等于用户设备 Gatekeeper 通过。
7. 全部满足后由维护者**手动 Publish Release**；确认官网按平台提供实际对应的安装包和 Release Notes。

当前文档是发布准备记录，**不代表 0.1.3 已发布或新安装包已通过验收**。正式发布流程见 [Desktop Release](DESKTOP.md#automatic-release-drafts)。
