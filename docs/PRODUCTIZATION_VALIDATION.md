# LeafLoom productization validation

Recorded on 2026-10-13, Windows x64. Existing staged AI work was retained. No repository visibility, user service, real note folder or real AI conversation was changed by the media fixture.

| Check | Result | Boundary |
| --- | --- | --- |
| Frontend | TypeScript and production build passed | Build warnings remain for existing large lazy chunks |
| Dependency lock | Offline lock check passed, 155 packages | No dependency upgrades |
| Catalogs | 670 authored entries; no missing literal UI keys; placeholder sets match | Chinese, English and Japanese |
| Preference/demo regressions | 3 tests passed | CSRF, independent preferences, unchanged configuration, legacy defaults, preserved demo edits, real trilingual keyword retrieval |
| Installer regressions | 22 tests passed | Mocked runtime/service/download operations; not a fresh machine install |
| Existing AI drafts | Passed | Autosave, manual AI drafts, reload, conflicts, discard, concurrent edits |
| Existing browsing contracts | Passed | Request deduplication, cancellation, 304, bounded caches, folder scope, resources, draft conflicts |
| Browser screenshots | 24 screenshots; 12 scenario checks; no page errors | Three languages; actual fictional-note retrieval, source navigation, graph, scope setup, responsive layout |
| Live draft language switch | 5 checks passed; no page errors | Unsaved manual draft stays off disk; memoized document translates, scroll/revision preserved, reload restores language and draft |
| Native source | Python, PowerShell and JXA syntax checked | Swift/AppKit requires macOS compilation and runtime validation |
| English video | 35 seconds, 1920×1080, 30 fps, H.264/AAC | Burned-in captions, separate SRT, original synthesized soundtrack |

Screenshots use a fresh browser profile, isolated loopback port and temporary state. Absolute environment paths are replaced on the page before capture. The AI demonstration is explicitly fictional, with external execution disabled. Search shows the real keyword/Wiki fallback: this run did not download BGE-M3 or verify semantic inference.

The updated macOS native menu binary has not been produced in this Windows run. The dedicated workflow is ready, but local GitHub CLI authentication is invalid. The localized AppKit compatibility menu is available until a revision-4 maintained binary is built. Finder, macOS login behavior and the compatibility menu require native verification; they are not reported as passed.

The Windows browser interface was visually inspected. Actual tray display, native directory chooser, re-login and a full cold installation were not exercised. Application build assets are prepared locally; updating the normally installed service still requires installation and restart.

See [media reproduction](MEDIA.md), [installation acceptance](INSTALL_VALIDATION.md) and [contributing](../CONTRIBUTING.md).

## Product film revision 2

The English film was rebuilt from five actual Edge browser recordings on the isolated fictional fixture. Sixteen real clicks cover editing and reading, typing a query and opening its source, selecting a graph note and exploring/zooming/panning its connections, previewing and accepting a fictional AI suggestion into an unsaved draft, and saving a Notes-only search scope. Assertions confirm the new note content, opened source, graph focus, manual-draft banner and saved scope. There were no browser page errors. Recording timecodes were aligned to actual video frames.

The 35-second edit uses eased camera pushes and pans, cursor/click overlays, chapter graphics and 0.3-second cross-dissolves. Key frames and a two-second contact sheet were inspected for legibility, operation framing and privacy; the draft banner and graph zoom button remain visible at their relevant moments. Assets use only fictional notes and a disabled external AI adapter; user notes and AI history were not opened.

FFprobe confirms 1920×1080, 30 fps, H.264 High, AAC stereo at 48 kHz and exactly 35.000 seconds. Full decoding completed with 1,050 video frames and no errors. The encoded audio measures −16.07 LUFS integrated and −2.20 dBTP. Audio verification covers decoding and measured levels; no subjective listening sign-off is recorded. Python/Node syntax and whitespace checks passed. No broader application or native platform checks were repeated for this media-only revision.

The reusable takes, action timecodes, scene/camera specification, original synthesized 120-BPM music, English SRT and cover are included. The previous cut is retained in the local ignored cache for comparison. Existing staged application work was retained.

## Product film revision 3: locked framing

Each of the five product scenes now uses a single 0.6-second entry push with one anchor, then holds the crop and zoom. Later camera keyframes, lateral title motion and the continuous brand-card zoom were removed. Actual interface actions remain in the original recordings.

A static-image check through the production camera expressions compared frames 18, 30 and 75 in every scene. Their frame hashes match exactly after the push, while frame 0 differs as expected. A contact sheet and key draft/scope frames were reviewed; the relevant buttons and unsaved-draft notice remain visible. The rebuilt film passes its 35-second, 1080p/30-fps H.264/AAC checks and full decoding. Python syntax and whitespace checks passed. No application or platform regression suite was rerun for this framing edit.

## Final media and repository preparation

The brand closing no longer displays a repository address. The writing take was recorded again with its heading and insertion line centered in the viewport. Extra trailing space is applied only to the isolated recording page, and does not modify application styles. The recorder asserts that writing begins in the central area, then records actual typing and switching to reading. The final set contains 15 real clicks, including two in the revised writing take; the other recordings and the locked camera policy are retained.

The repository entry points and package links target `DJ-Huang/LeafLoom`. Existing current files and Git history were checked for recognizable private-key and provider-token patterns; none were found. Local environment files, generated configuration, indexes and caches remain excluded. This is a focused publication check, not a comprehensive security audit.
