# LeafLoom 0.1.8 — Design Studio workflows and Markdown outlines

Release date: 2026-11-05 · Changes since v0.1.7

[English](RELEASE_NOTES_0.1.8.md) · [中文](../zh-CN/RELEASE_NOTES_0.1.8.md) · [日本語](../ja/RELEASE_NOTES_0.1.8.md)

## Organize and compare designs

Group pages into collapsible folders, move multiple pages, rename or merge folders and restore pages to the ungrouped list. Collapse the layers and properties panels independently. In **Compare** mode, edit on the left while an interactive preview on the right refreshes after saved changes.

## Copy images and element locations

Copy a single source image as PNG with its original dimensions and transparency, including bound and variant images, without changing the project. Copy compact locations for one or multiple selected elements with Cmd+C / Ctrl+C, the context menu or inspector. Normal text and source editing copy behavior remains available. Restart LeafLoom after upgrading to use the updated desktop clipboard bridge.

## Navigate Markdown notes

The new collapsible page outline follows the current section, supports folding heading subtrees and jumping to headings in page or source mode, and updates as you edit. In narrow panes it opens as an overlay.

## More efficient attachment synchronization

Directory scans adapt to activity, while uploads trigger targeted checks. Idle metadata and group pulls and failed retries back off, schedules survive restarts, and externally deleted cached directories can recover. A manual full check still runs immediately.

## Upgrade and availability

Back up your vault and metadata, quit LeafLoom, install the matching package and reopen the same vault. Source users should update and restart LeafLoom. Installers target Windows x64 and macOS 14+ Apple Silicon. Windows is unsigned; macOS uses ad-hoc signing without Apple notarization. Check the release assets, SHA256SUMS.txt and build results for this version.

[User guide](GUIDE.md) · [Full changelog](../../CHANGELOG.md)
