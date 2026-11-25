# Public website · 官网维护 · 公式サイト

[Website](https://dj-huang.github.io/LeafLoom/) · [中文](https://dj-huang.github.io/LeafLoom/zh-CN/) · [日本語](https://dj-huang.github.io/LeafLoom/ja/) · [Documentation](README.md)

## Source and build

`site/page.html`, `site/about.html`, `site/style.css` and `site/help/` form an independent static marketing website and help center. It does not load the application frontend, run the Python service, access vaults, or include analytics. English is the root page; Chinese and Japanese have `/zh-CN/` and `/ja/` routes. Each language has an `about/` page linked from the navigation and footer, with the creator’s GitHub and X profiles. Help lives under `/docs/{en,zh-CN,ja}/`. Language links and canonical/alternate metadata retain the current page type; all six marketing pages and 132 help routes appear in the sitemap. All articles support direct loading without JavaScript.

Author all website UI copy under `site.*` keys in `vault_rag/locales/messages.tsv`; do not edit generated catalogs or HTML. Run these commands from the repository root with Python 3.12+. The small, pinned Markdown renderer is independent of the application's model/desktop dependencies:

```sh
python -m pip install -r site/requirements.txt
python scripts/compile_locales.py
python -m unittest discover -s tests -p test_site.py -v
python -m unittest discover -s tests -p test_docs.py -v
python scripts/build_site.py
```

Output is `dist/site/`, ignored by Git. The build copies only selected brand assets, public screenshots and the existing public English demo MP4; it does not copy the repository or runtime state. Screenshots come from `assets/screenshots/{en,zh-CN,ja}/`, with the public-media constraints in [MEDIA.md](MEDIA.md). AI demo labels must remain visible.

The homepage serves `assets/promo/leafloom-en.mp4` from the same Pages origin with native controls, inline playback, no autoplay and no video preload. Localized hero screenshots remain the posters; all languages label the video as English and provide a direct link. The MP4 already includes burned-in English captions. Video changes also trigger the Pages workflow.

中文：三语首页通过同源 MP4 播放现有英文演示视频，保留各语言截图封面和直达链接，不自动播放或预加载视频。

日本語：3 言語のトップページで既存の英語デモを同一オリジンの MP4 として再生し、各言語のポスターと直接リンクを提供します。自動再生や動画の事前読み込みは行いません。

To preview with the production `/LeafLoom/` prefix:

```sh
python scripts/build_site.py --output .cache/site-preview/LeafLoom
python -m http.server 18092 --bind 127.0.0.1 --directory .cache/site-preview
```

Open `http://127.0.0.1:18092/LeafLoom/`. `--base-url` overrides the canonical origin and prefix for a different host. Stop the preview server after use. For offline reproduction, save the public response from `GET https://api.github.com/repos/DJ-Huang/LeafLoom/releases/latest` and pass `--release-json path/to/release.json`. To reproduce platform fallbacks offline, add a `fallback_releases` array containing the historical Release objects from the paginated releases API.

## Help center

`docs/help/navigation.json` owns topic order and source selection. There are 39 task articles per language under `docs/{en,zh-CN,ja}/help/`, plus the existing full user guide, AI guide, changelog and release notes. Existing sources retain their paths. `scripts/build_docs.py` renders these into the same Pages artifact as the homepage; `/docs/` offers language entry links and defaults to English. The website navigation, AI/privacy links and application sidebar point to localized help.

Every task article has one H1 and six H2 sections: goal, prerequisites, steps, expected result, troubleshooting and next steps. Their anchors are `goal`, `before`, `steps`, `result`, `troubleshooting`, `next` in every language, so language switching retains an article and its standard section. Add the same slug in all three languages and list it in navigation. Article content belongs in Markdown; help interface copy belongs under `site.help_*` in `messages.tsv`. Keep examples fictional. When behavior changes, update the relevant task article as well as the three complete guides and changelogs.

The help homepage includes grouped topics and three starting paths. Article pages include breadcrumbs, a page contents list, previous/next links and a repository source link. CSS handles phone layouts; JavaScript adds an accessible mobile topic toggle, local full-text search (`Ctrl/⌘+K`), code-copy buttons and image zoom. Without JavaScript, articles and topic navigation remain available. Search downloads only the current language's generated `search.json`; there is no remote search provider, analytics, application API or vault access. Failed searches can be retried without reloading the page.

The renderer escapes raw HTML, rejects unsafe URLs and missing repository links, and copies only referenced images from the public screenshot/brand/document asset directories. Markdown links to included sources become site routes, while technical references stay on GitHub. All three languages must have every article; a missing source or translation fails the build. `tests/test_docs.py` validates coverage, standard section anchors, duplicate IDs, local links, cross-page fragments, media, prefixes and URL boundaries. `docs/**`, changelogs and help source changes trigger PR checks and main-branch deployment through the existing Pages workflow. PRs do not deploy.

中文：帮助中心位于 `/docs/zh-CN/`，提供 39 篇任务指南与 4 篇完整指南／版本参考，覆盖分类导航、全文搜索、页内目录、前后篇、图片放大与示例复制。正文在各语言 `help/` 中维护，界面文案在 `messages.tsv`，导航顺序在 `docs/help/navigation.json`。更新功能时同时维护任务文章、完整指南与更新记录。文档变动自动触发 Pages；只发布静态公开内容，不接触本地知识库。

日本語：`/docs/ja/` に 39 件のタスク記事と 4 件の全体ガイド／更新資料を提供します。分類・全文検索・目次・前後の記事・画像拡大・例のコピーに対応。本文は言語別 `help/`、UI 文言は `messages.tsv`、順序は `docs/help/navigation.json` で管理します。機能変更時は記事・全体ガイド・変更履歴を更新してください。文書の変更も Pages を起動し、公開用の静的内容のみを配信します。

## Downloads

The build queries the latest published, non-prerelease GitHub Release. If it lacks an installer for either platform, the build reads the paginated release history and selects the highest earlier stable version that provides that platform’s installer. Drafts, prereleases and unsupported version tags are excluded. An optional `GITHUB_TOKEN` environment variable authenticates CI API requests; it is never written into the output. Failed API requests fail the build and preserve the previous live site instead of inventing download links.

For a tag `vX.Y.Z`, assets must follow the existing desktop packaging convention:

- `LeafLoom-X.Y.Z-windows-x64-setup.exe`
- `LeafLoom-X.Y.Z-macos-arm64.dmg`
- `SHA256SUMS-windows.txt` for Windows when present, otherwise `SHA256SUMS.txt`; Mac uses `SHA256SUMS.txt`.

Buttons link to the actual public asset URLs, not a browser-side API lookup. Each platform displays its actual installer version and links to that version’s release notes and checksum; the featured release remains the latest stable Release. A platform is labeled unavailable only when no eligible stable Release provides its installer, and **All releases** remains accessible. Checksums are linked only when the corresponding file exists in the selected installer’s Release. Installers remain on GitHub Releases; they are not duplicated in Pages. Keep platform requirements and signing information aligned with the installer documentation.

Upload all assets before publishing a Release. A stable Release's **published** event automatically rebuilds and deploys the homepage with its new downloads; deleting a Release also rebuilds the site. The workflow intentionally avoids the redundant `released` and `edited` triggers, which generated three competing runs when v0.1.3 was published. Release edits or asset uploads after publication require manually running **LeafLoom website** (`workflow_dispatch`) because they do not affect the published-event hook. Preview releases never become the featured download. After deployment, inspect the live homepage in all three languages and verify each platform download and checksum link points to the intended release. A successful deployment alone does not confirm that the live page has changed; compare the generated Pages artifact with the live response if it still shows an older version.

For a published stable Release, the build checks that GitHub's `releases/latest` has caught up to at least the published tag, retrying for up to 25 seconds. If it remains stale, the job fails **without deploying outdated links**. The production build/deploy workflows are serialized; PR builds use separate concurrency groups. GitHub Pages serves static HTML with a cache lifetime (observed `Cache-Control: max-age=600`), so a previously open browser can briefly retain the old version even after successful deployment. Hard-refresh or reopen the page to check.

## GitHub Pages deployment

`.github/workflows/pages.yml` builds on relevant pushes to `main`, Release publication/deletion events, and manual dispatch. Pull requests run the same build and focused tests, but skip deployment. Release events always build current `main`, rather than the older release tag. The workflow uses GitHub's official Pages artifact and deployment actions.

Enable **Settings → Pages → Source → GitHub Actions**. In **Settings → Environments → github-pages → Deployment branches and tags**, allow the `main` branch and `v*` tags. Release workflows retain the triggering tag as their deployment ref even though checkout builds current main; allowing only main rejects those deployments. Deployment uses the `github-pages` environment and `pages: write` / `id-token: write` only in its deployment job. The site URL is `https://dj-huang.github.io/LeafLoom/`; no custom domain is configured. After changing website copy, images, templates or download conventions, merge a PR and inspect the **LeafLoom website** workflow. The manual workflow is also the recovery path after correcting a Release's assets. A failed deployment leaves the previous published version available.

For rollback, revert the website change through a PR and redeploy. Do not force-push main or copy the whole repository into a Pages artifact. Verify all three routes, phone/desktop layout, release version and installer links after deployment.

## Main branch protection

`main` requires a pull request, with zero required approvals so the maintainer can merge their own PR. Conversations must be resolved, force pushes and deletion are disabled, and administrators follow the same rules. No required status checks, signed commits or linear-history restriction are configured. Existing workflows can be manual-only or path-filtered; they must not be required globally without guaranteeing they run for every PR. Read back protection through the GitHub API after changing these settings.

## 中文

官网正文维护在 `messages.tsv` 的 `site.*` 三语条目中，通过现有翻译编译器与 `scripts/build_site.py` 生成独立静态页面。使用上方命令构建和预览，生成内容位于被忽略的 `dist/site/`，不要直接编辑。下载信息来自最新正式 Release 的实际资源；新 Release 缺少某平台安装包时，继续提供该平台最新可用正式版，并显示该版版本、说明和校验文件；仅在没有可用正式安装包时显示暂不可用。先上传完整安装包再发布 Release；若给已发布版本补传资源，需手动重新运行 **LeafLoom website**。Pages 环境允许 main 分支和 v* 标签部署，确保 Release 事件可自动发布。通过 PR 合入 main 后部署，PR 本身不发布。main 禁止强推和删除，管理员也必须走 PR，但无需其他人批准。

## 日本語

本文は `messages.tsv` の `site.*` キーで日英中を管理し、既存の翻訳コンパイラーと `scripts/build_site.py` で独立した静的ページを生成します。上記のコマンドでビルド・プレビューでき、生成先の `dist/site/` は直接編集しません。ダウンロードは最新正式 Release の実在するアセットを参照。新しい Release に対象のアセットがない場合は、利用できる最新正式版とその版のバージョン・ノート・チェックサムを掲載し、正式版のインストーラーがない場合のみ利用不可になります。すべてのアセットをアップロードしてから Release を公開し、公開済み版への追加アップロード後は **LeafLoom website** を手動実行します。Pages 環境で main ブランチと v* タグを許可し、Release イベントからも自動公開します。PR の main へのマージ後に公開され、PR 自体はデプロイしません。main の強制プッシュと削除は禁止。管理者も PR を使いますが、他者の承認は必須ではありません。

## Live-site mismatch runbook

Use this read-only procedure when **LeafLoom website** reports success but the public downloads remain old. Do not treat a successful deployment, a shared commit SHA, or a repeated deployment ID as proof of which HTML is being served.

1. Record the latest stable Release, actual platform assets and checksum filenames. Check the per-platform fallback rules above before calling an older installer a fault.
2. Record both the previous and new workflow run IDs, their `github-pages` artifact IDs and expiry times. Download the ZIPs before expiry and retain their SHA-256 hashes. Inside each ZIP, read `artifact.tar` and compare `index.html`, `zh-CN/index.html` and `ja/index.html`. Compare the bytes and download URLs, not only the source commit.
3. Fetch those three public pages with a fresh query parameter and `Cache-Control: no-cache`. Save the raw response body, UTC time, URL, status and cache headers (`Date`, `Last-Modified`, `ETag`, `Age`, `Cache-Control`, `Via`, `X-Cache`). Hash the bodies and compare each with both artifacts. A cache-busting request is diagnostic, not a guarantee that every intermediary bypassed its cache.
4. If needed, make at most three rounds, five minutes apart, with a 20-second timeout per request. Treat this as a bounded observation window, not a promised propagation deadline. Report timeouts separately from a verified old response; do not loop indefinitely or automatically redeploy.
5. Read the deployment log's submitted `artifact_id` and reported status. Distinguish **generated content**, **submitted artifact**, **reported deployment success**, and **observed public bytes**. If Pages status access is unavailable, record that limitation rather than inferring the serving association from its ID.

| Evidence | Next step |
| --- | --- |
| New artifact itself contains unexpected old links | Reproduce the build with the saved release JSON; check missing assets and fallback selection before proposing a code change. |
| New artifact is correct, public bytes match the old artifact | Keep the evidence and investigate deployment/hosting/cache state. Do not hard-code a new version into the page template. |
| Public bytes match the new artifact in all languages | Record convergence and stop the follow-up; no repair is needed. |
| Fetch fails or matches neither artifact | Record the failure or differing content and check for a newer deployment; do not label it a cache failure without evidence. |

Until the mismatch is resolved, direct users to the verified [GitHub Releases page](https://github.com/DJ-Huang/LeafLoom/releases), stating the intended version and platform. A link check or checksum-file read is not an installer hash verification or an installation test. Any rerun, redeployment, rollback or settings change is a separate action requiring the maintainer's authorization; this diagnostic procedure makes none of those changes.

### 中文：线上版本不一致排查

部署成功不等于公网已更新；相同提交 SHA 或部署 ID 也不能证明实际服务的内容。先确认正式 Release 的实际安装包和校验文件，区分合法的平台旧版回退。保存前后两次运行的 artifact ID、到期时间与 ZIP 哈希，在到期前下载；比较 `artifact.tar` 内三语首页的字节和链接。再保存公网三语首页的原始响应、UTC 时间和缓存头，与两份产物逐字节比较。带新查询参数及 no-cache 的请求也不能证明所有中间缓存已绕过。

最多检查三轮、每轮间隔五分钟、每次请求超时二十秒；这是观察窗口，不是传播时限保证。分别记录生成产物、实际提交的 artifact ID、部署报告和公网内容。新产物正确但线上匹配旧产物时，继续核对托管／部署／缓存状态，不硬编码版本、不自动重部署；状态接口不可用就明确记录限制。三语均匹配新产物后停止跟进。期间提供已核验版本的 GitHub Releases 下载入口，不把校验文件可读当成安装包哈希或原生安装验证。重跑、部署、回滚和设置变更均需另行获得维护者授权。

### 日本語：公開ページのバージョン不一致

デプロイ成功は公開内容の更新を保証しません。同じコミット SHA やデプロイ ID だけで配信中の内容を判断しないでください。正式 Release の実際のアセットとチェックサムを確認し、正当なプラットフォーム別フォールバックを区別します。新旧 run の artifact ID・期限・ZIP ハッシュを記録し、期限前に保存します。`artifact.tar` 内の 3 言語のトップページを取り出し、公開レスポンスのバイト列・リンクと比較します。UTC 時刻とキャッシュヘッダーも保存してください。新しいクエリ文字列と no-cache は、全中継キャッシュの回避を保証しません。

確認は最大 3 回、5 分間隔、各リクエストのタイムアウトは 20 秒とします。これは観測時間であり反映期限の保証ではありません。生成物、送信した artifact ID、デプロイ結果、公開内容を分けて記録します。新しい生成物が正しくても公開内容が古い場合は、ホスティング・配信・キャッシュを調査し、バージョンの直書きや自動再デプロイはしません。状態 API にアクセスできなければ、その制限を報告します。全言語が新しい生成物と一致したら確認を終了します。それまでは検証済みの GitHub Releases を案内してください。チェックサムファイルの取得はインストーラーのハッシュ検証やインストール試験とは異なります。再実行・再デプロイ・ロールバック・設定変更には別途メンテナーの承認が必要です。
