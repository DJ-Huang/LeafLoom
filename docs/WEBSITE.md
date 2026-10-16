# Public website · 官网维护 · 公式サイト

[Website](https://dj-huang.github.io/LeafLoom/) · [中文](https://dj-huang.github.io/LeafLoom/zh-CN/) · [日本語](https://dj-huang.github.io/LeafLoom/ja/) · [Documentation](README.md)

## Source and build

`site/page.html`, `site/about.html` and `site/style.css` form an independent, static marketing website. It does not load the application frontend, run the Python service, access vaults, or include analytics. English is the root page; Chinese and Japanese have `/zh-CN/` and `/ja/` routes. Each language has an `about/` page linked from the navigation and footer, with the creator’s GitHub and X profiles. Language links and canonical/alternate metadata retain the current page type; all six pages appear in the sitemap. All routes support direct loading without JavaScript.

Author all website UI copy under `site.*` keys in `vault_rag/locales/messages.tsv`; do not edit generated catalogs or HTML. Run these commands from the repository root with Python 3.12+ (standard library only):

```sh
python scripts/compile_locales.py
python -m unittest discover -s tests -p test_site.py -v
python scripts/build_site.py
```

Output is `dist/site/`, ignored by Git. The build copies only selected brand assets and public screenshots; it does not copy the repository or runtime state. Screenshots come from `assets/screenshots/{en,zh-CN,ja}/`, with the public-media constraints in [MEDIA.md](MEDIA.md). AI demo labels must remain visible.

To preview with the production `/LeafLoom/` prefix:

```sh
python scripts/build_site.py --output .cache/site-preview/LeafLoom
python -m http.server 18092 --bind 127.0.0.1 --directory .cache/site-preview
```

Open `http://127.0.0.1:18092/LeafLoom/`. `--base-url` overrides the canonical origin and prefix for a different host. Stop the preview server after use. For offline reproduction, save the public response from `GET https://api.github.com/repos/DJ-Huang/LeafLoom/releases/latest` and pass `--release-json path/to/release.json`. To reproduce platform fallbacks offline, add a `fallback_releases` array containing the historical Release objects from the paginated releases API.

## Downloads

The build queries the latest published, non-prerelease GitHub Release. If it lacks an installer for either platform, the build reads the paginated release history and selects the highest earlier stable version that provides that platform’s installer. Drafts, prereleases and unsupported version tags are excluded. An optional `GITHUB_TOKEN` environment variable authenticates CI API requests; it is never written into the output. Failed API requests fail the build and preserve the previous live site instead of inventing download links.

For a tag `vX.Y.Z`, assets must follow the existing desktop packaging convention:

- `LeafLoom-X.Y.Z-windows-x64-setup.exe`
- `LeafLoom-X.Y.Z-macos-arm64.dmg`
- `SHA256SUMS-windows.txt` for Windows when present, otherwise `SHA256SUMS.txt`; Mac uses `SHA256SUMS.txt`.

Buttons link to the actual public asset URLs, not a browser-side API lookup. Each platform displays its actual installer version and links to that version’s release notes and checksum; the featured release remains the latest stable Release. A platform is labeled unavailable only when no eligible stable Release provides its installer, and **All releases** remains accessible. Checksums are linked only when the corresponding file exists in the selected installer’s Release. Installers remain on GitHub Releases; they are not duplicated in Pages. Keep platform requirements and signing information aligned with the installer documentation.

Upload all assets before publishing a Release; upload assets for an already-published Release before manually running the website workflow again. Release publication/edit/release/deletion events refresh the site, but individual asset uploads do not trigger the workflow. Preview releases never become the featured download; rebuilding still selects the latest stable Release.

## GitHub Pages deployment

`.github/workflows/pages.yml` builds on relevant pushes to `main`, Release events, and manual dispatch. Pull requests run the same build and focused tests, but skip deployment. Release events always build current `main`, rather than the older release tag. The workflow uses GitHub's official Pages artifact and deployment actions.

Enable **Settings → Pages → Source → GitHub Actions**. In **Settings → Environments → github-pages → Deployment branches and tags**, allow the `main` branch and `v*` tags. Release workflows retain the triggering tag as their deployment ref even though checkout builds current main; allowing only main rejects those deployments. Deployment uses the `github-pages` environment and `pages: write` / `id-token: write` only in its deployment job. The site URL is `https://dj-huang.github.io/LeafLoom/`; no custom domain is configured. After changing website copy, images, templates or download conventions, merge a PR and inspect the **LeafLoom website** workflow. The manual workflow is also the recovery path after correcting a Release's assets. A failed deployment leaves the previous published version available.

For rollback, revert the website change through a PR and redeploy. Do not force-push main or copy the whole repository into a Pages artifact. Verify all three routes, phone/desktop layout, release version and installer links after deployment.

## Main branch protection

`main` requires a pull request, with zero required approvals so the maintainer can merge their own PR. Conversations must be resolved, force pushes and deletion are disabled, and administrators follow the same rules. No required status checks, signed commits or linear-history restriction are configured. Existing workflows can be manual-only or path-filtered; they must not be required globally without guaranteeing they run for every PR. Read back protection through the GitHub API after changing these settings.

## 中文

官网正文维护在 `messages.tsv` 的 `site.*` 三语条目中，通过现有翻译编译器与 `scripts/build_site.py` 生成独立静态页面。使用上方命令构建和预览，生成内容位于被忽略的 `dist/site/`，不要直接编辑。下载信息来自最新正式 Release 的实际资源；新 Release 缺少某平台安装包时，继续提供该平台最新可用正式版，并显示该版版本、说明和校验文件；仅在没有可用正式安装包时显示暂不可用。先上传完整安装包再发布 Release；若给已发布版本补传资源，需手动重新运行 **LeafLoom website**。Pages 环境允许 main 分支和 v* 标签部署，确保 Release 事件可自动发布。通过 PR 合入 main 后部署，PR 本身不发布。main 禁止强推和删除，管理员也必须走 PR，但无需其他人批准。

## 日本語

本文は `messages.tsv` の `site.*` キーで日英中を管理し、既存の翻訳コンパイラーと `scripts/build_site.py` で独立した静的ページを生成します。上記のコマンドでビルド・プレビューでき、生成先の `dist/site/` は直接編集しません。ダウンロードは最新正式 Release の実在するアセットを参照。新しい Release に対象のアセットがない場合は、利用できる最新正式版とその版のバージョン・ノート・チェックサムを掲載し、正式版のインストーラーがない場合のみ利用不可になります。すべてのアセットをアップロードしてから Release を公開し、公開済み版への追加アップロード後は **LeafLoom website** を手動実行します。Pages 環境で main ブランチと v* タグを許可し、Release イベントからも自動公開します。PR の main へのマージ後に公開され、PR 自体はデプロイしません。main の強制プッシュと削除は禁止。管理者も PR を使いますが、他者の承認は必須ではありません。
