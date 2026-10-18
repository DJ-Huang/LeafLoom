# LeafLoom 0.1.3 — 版本说明

[English](../en/RELEASE_NOTES_0.1.3.md) · [日本語](../ja/RELEASE_NOTES_0.1.3.md) · [文档目录](../README.md)

本次更新相较于 [v0.1.2](https://github.com/DJ-Huang/LeafLoom/releases/tag/v0.1.2)，重点是 Design Studio、可选飞书 MCP 工具及 Windows/macOS 双平台发布流程。

## 主要更新

- **Design Studio：** 提供多画板编辑、图层、组件、响应式布局、文字排版、样式、图片裁切、动画和受控脚本；新增 FORMA、Motion Playground、ATELIER 可编辑模板。「编辑 / 预览」直达并恢复页面、选区和视角，保留原始 HTML 与隔离预览。
- **多语言与发布：** 稳定键文字/图片绑定、中英日变体与布局覆盖、溢出及素材/字形预检，可按页面和变体批量导出 PNG ZIP、多页 PDF，支持进度和重试。脚本/动画请继续使用交互式 HTML/ZIP。
- **编辑可靠性：** 持久撤销/重做、版本冲突校验、未保存内容恢复，目录选择不直接创建项目；回收站永久删除需确认。
- **MCP 与飞书：** 共 42 个 HTTP MCP 工具：笔记 23、Design Studio 14、可选飞书 5。飞书需自行安装并授权 `lark-cli`，笔记与飞书权限独立。升级后刷新客户端工具列表。
- **开发与官网：** 新增隔离的浏览器开发入口及可选 `--loopback-ui`，常规桌面和 MCP 默认端口 18080 不变。三语官网增加 About 页面和可播放演示视频，按系统分别提供最新稳定安装包。
- **发布：** 匹配版本的 Tag 自动构建 Windows x64、Apple Silicon macOS 安装包并校验 SHA-256，仅生成未公开草稿，必须人工审核发布。

## 兼容性与限制

- 支持 Windows 10/11 x64、macOS 14+ Apple Silicon。请正常退出后再升级；笔记、设置、索引和模型会保留。
- 将受支持的旧 HTML 作品转换为**独立副本**，不覆盖原始文件；复杂脚本及动态状态可能仍需手动适配。
- PNG/PDF 为静态导出，不执行脚本与动画；含嵌入 HTML、动态素材请用交互式 HTML。字体、离线资源、体量和字形检测限制见 [Design Studio 文档](../DESIGN_STUDIO.md)。
- 浏览器开发入口不等于 Linux 安装版；Mac 原生发布验收通过也不代表打包后的 Windows 原生发布已验收。
- Windows 安装包未签名、Mac 临时签名且未公证，可能遇到 SmartScreen/Gatekeeper 警告或拦截。
- **不包含附件集中迁移：** [PR #18](https://github.com/DJ-Huang/LeafLoom/pull/18) 尚未合并，本次不会迁移笔记附件。

## PR 范围与发布确认

上次正式发布后已合并 [#10](https://github.com/DJ-Huang/LeafLoom/pull/10)、[#11](https://github.com/DJ-Huang/LeafLoom/pull/11)、[#12](https://github.com/DJ-Huang/LeafLoom/pull/12)、[#13](https://github.com/DJ-Huang/LeafLoom/pull/13)、[#14](https://github.com/DJ-Huang/LeafLoom/pull/14)、[#15](https://github.com/DJ-Huang/LeafLoom/pull/15)、[#16](https://github.com/DJ-Huang/LeafLoom/pull/16)、[#17](https://github.com/DJ-Huang/LeafLoom/pull/17)，另含直接提交。#17 的 Design Studio、HTML 和官网 CI 已通过；**v0.1.3 的最终安装包仍需 Tag 构建及人工验收**。

发布前检查双平台安装包和 `SHA256SUMS.txt`，然后人工 Publish。详见[桌面发布说明](../DESKTOP.md#automatic-release-drafts)与[发布前检查](../RELEASE_PREP_0.1.3.md)。
