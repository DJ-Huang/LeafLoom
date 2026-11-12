# LeafLoom 0.1.9 - Calendar, unified skill and faster attachments

Release date: 2026-11-12 · Changes since v0.1.8

[English](RELEASE_NOTES_0.1.9.md) · [中文](../zh-CN/RELEASE_NOTES_0.1.9.md) · [日本語](../ja/RELEASE_NOTES_0.1.9.md)

## Plan with Calendar

Use month, day and agenda views alongside shared daily notes, recurring items and database tasks. Calendar files synchronize through your vault with conflict handling, recoverable deletion and a verified migration backup. Reminder settings and delivery history stay on each device; keep `.vault-rag` out of file synchronization.

Legacy Calendar migration on Windows also fixes a backup-flush failure while preserving the verified backup and calendar data.

## One LeafLoom skill

The installable skill brings together local search, tasks, work capture and Design Studio. Work records include both structured activities and the human-readable period log; missing hours are requested before saving. Weekly reports default to concise, manager-facing Markdown. Installation retires superseded skills while keeping local backups.

On Windows, a new PowerShell entry point selects Python 3.11+ and preserves Unicode, quotes, paths and nested JSON arguments without manual escaping. It avoids Microsoft Store aliases and does not retry failed writes automatically.

## Browse attachments with less waiting

Local and server sources load independently, so an unavailable server no longer hides local files or resets filters and pagination. An app-owned server membership catalog reduces full-tree discovery. Note-sized pasted images can remain as local vault cache, while larger files use lightweight previews. Valid local caches open immediately while server versions are checked in the background. Server migration supports resumable batches and visible transfer and verification progress; HTML and Design Studio project assets stay within their project folders.

Copy note images as PNG from the context menu or with Ctrl/Cmd+C. Image actions now share one menu, and path-bar copying works when the browser clipboard API is unavailable.

Fix attachment reference synchronization treating membership-catalog child records as references. Resuming migration preserves confirmed mapping and cleanup stages, avoids re-uploading already verified transfers, and stops rather than removing a locally changed replacement file.

## Design Studio and publishing

Use public website links in preview, comparison and presentation. Valid external source edits become one undoable step. Miaoda publication handles temporary status failures and interrupted uploads more reliably, with clearer loading and recovery behavior.

## Upgrade and availability

Back up your vault and metadata, quit LeafLoom, install the matching package and reopen the same vault. Source users should update and restart LeafLoom. Installers target Windows x64 and macOS 14+ Apple Silicon. Windows is unsigned; macOS uses ad-hoc signing without Apple notarization. Check this release's assets, SHA256SUMS.txt and build results before installation.

[User guide](GUIDE.md) · [Full changelog](../../CHANGELOG.md)
