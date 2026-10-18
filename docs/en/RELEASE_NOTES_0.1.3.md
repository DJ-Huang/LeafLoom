# LeafLoom 0.1.3 — Release Notes

[简体中文](../zh-CN/RELEASE_NOTES_0.1.3.md) · [日本語](../ja/RELEASE_NOTES_0.1.3.md) · [Docs](../README.md)

Compared with [v0.1.2](https://github.com/DJ-Huang/LeafLoom/releases/tag/v0.1.2), this release substantially expands Design Studio, adds optional Feishu MCP tools and prepares a single Windows/macOS release flow.

## Highlights

- **Design Studio:** Editable multi-page HTML/design workbench with FORMA, Motion Playground and ATELIER templates, reusable components, layouts, styling, image cropping, animations and scoped scripts. Direct **Edit / Preview** switching preserves your page, selection and camera; original HTML and isolated interactive previews remain available.
- **Languages and publishing:** Stable text/image bindings, English/Chinese/Japanese variants and per-variant layouts. Run overflow, resource and glyph-risk preflight; batch-export selected pages/variants to PNG ZIP or multi-page PDF, with progress/retry. Keep interactive HTML/ZIP export for scripts and motion.
- **Recovery:** Persistent undo/redo across document changes, revision checks, pending-save recovery, explicit project creation and guarded Design Studio trash deletion.
- **MCP / Feishu:** 42 HTTP MCP tools: 23 note tools, 14 Design Studio tools and 5 optional Feishu tools. Feishu requires a separately installed and authorized `lark-cli`; note and Feishu permissions remain independent. Refresh your client's MCP tool list after upgrading.
- **Development and website:** Optional isolated browser developer mode with `--loopback-ui`; ordinary desktop and MCP port 18080 are unchanged. Trilingual website adds an About page, working demo video and the latest stable installer per OS.
- **Distribution:** A matching stable tag builds Windows x64 and macOS Apple Silicon installers with SHA-256 verification, producing an **unpublished Release draft** for manual approval.

## Compatibility and limitations

- Windows 10/11 x64 and macOS 14+ Apple Silicon are the supported installers. Quit LeafLoom normally before updating; notes, settings, models and indexes are preserved.
- Older supported HTML projects are converted into an **independent copy**, not overwritten. Some original dynamic behavior and scripts require manual adaptation.
- PNG/PDF exports are static and do not execute scripts/motion; use interactive HTML export for embedded HTML or animated resources. Offline-resource, bounded-size, font/glyph and overflow limitations are detailed in [Design Studio](../DESIGN_STUDIO.md).
- The browser developer entry is **not** a Linux native installer. CI's macOS native-publishing acceptance is not proof of packaged Windows publishing acceptance.
- Windows packages are **unsigned**; macOS uses ad-hoc signing without notarization. SmartScreen/Gatekeeper may warn or block installation.
- **Attachment consolidation is not included:** [PR #18](https://github.com/DJ-Huang/LeafLoom/pull/18) remains unmerged. No existing vault attachments are migrated by this release.

## Change scope and final release checks

Merged since v0.1.2: [#10](https://github.com/DJ-Huang/LeafLoom/pull/10), [#11](https://github.com/DJ-Huang/LeafLoom/pull/11), [#12](https://github.com/DJ-Huang/LeafLoom/pull/12), [#13](https://github.com/DJ-Huang/LeafLoom/pull/13), [#14](https://github.com/DJ-Huang/LeafLoom/pull/14), [#15](https://github.com/DJ-Huang/LeafLoom/pull/15), [#16](https://github.com/DJ-Huang/LeafLoom/pull/16) and [#17](https://github.com/DJ-Huang/LeafLoom/pull/17), plus direct branch commits. PR #17's final Design Studio, HTML and website checks passed. **v0.1.3 native installers must still pass the tag-triggered workflow and human review before public release.**

Inspect both installers and `SHA256SUMS.txt` in the draft. See [desktop release instructions](../DESKTOP.md#automatic-release-drafts) and [release preparation](../RELEASE_PREP_0.1.3.md).
