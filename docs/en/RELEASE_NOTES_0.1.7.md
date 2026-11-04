# LeafLoom 0.1.7 — A work hub and more reliable asset collection

Release date: 2026-11-02 · Changes since v0.1.6

[English](RELEASE_NOTES_0.1.7.md) · [中文](../zh-CN/RELEASE_NOTES_0.1.7.md) · [日本語](../ja/RELEASE_NOTES_0.1.7.md)

## Capture work across projects

Install or update `work-hub` from **Settings → Skill**, then use it in your AI assistant to record work, link projects, manage local tasks and prepare reports. LeafLoom stores the records and original evidence in your vault. Reports use recorded facts and explicit hours, preserve personal edits and can follow your own weekly template. Office connections are optional.

## Choose more than one office platform

**Work hub settings** and chat share one version-checked configuration note. Check multiple platforms, or choose automatic source selection or local-only mode. Existing single selections remain readable. Feishu imports and task synchronization and specified GitLab activity imports are supported; DingTalk, WeCom and Notion currently store preferences only and are marked not integrated. Platform selection never grants remote-write permissions or expands collection scope.

## Mirror selected Feishu pages

On request, mirror a page and its children into a readable work directory. Images and videos are streamed to the attachment server and references change only after size/hash verification. Checkpoints preserve progress, local edits and copies of removed source pages. The optional mirror needs local LeafLoom, Python 3.11+, authenticated lark-cli and an attachment server.

## Collect Unity catalog metadata with more control

Preview selected attachment groups, limit and pace batches, and refresh linked products missing metadata. Official reads run with at most three concurrent requests; rate limits and access challenges stop new requests while preserving checkpoints. Transient errors can retry, empty search results remain valid, and missing public fields do not erase known facts or personal curation. Local catalog projections and WebDAV folder checks avoid unnecessary full-directory work. Collection does not download purchased packages or import them into Unity.

## Everyday improvements and server guidance

Copy relative or absolute paths from the top path bar, including keyboard navigation and clipboard feedback. New three-language DUFS setup and isolation guidance includes a reproducible symlink patch and verification harness; it does not automatically migrate user files or change server accounts.

## Upgrade and availability

Back up your vault and metadata, quit LeafLoom, install the matching package and reopen the same vault. Source users should update and restart LeafLoom. Update the work-hub Skill separately in Settings and refresh your AI client's skill discovery. Existing work records are not bulk migrated.

Installers target Windows x64 and macOS 14+ Apple Silicon. Windows is unsigned; macOS uses ad-hoc signing without Apple notarization. Consult the actual release assets, SHA256SUMS.txt and native workflow results; documentation does not certify untested devices or office integrations.

[User guide](GUIDE.md) · [Full changelog](../../CHANGELOG.md)
