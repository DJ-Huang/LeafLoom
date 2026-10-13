# Public screenshots and English video

[Screenshot gallery](../assets/screenshots/index.html) · [English video](../assets/promo/leafloom-en.mp4) · [Captions](../assets/promo/leafloom-en.srt)

The media uses fictional, multilingual demo notes. No user's vault, conversation or token is included. AI responses are clearly marked fictional, and the fixture disables external CLI execution. Search and graphs come from actual demo files; search uses the real keyword fallback when the semantic model is not installed.

## Reproduce

1. Use a working Python 3.12 environment with application dependencies. Compile catalogs with `python scripts/compile_locales.py`, generate examples with `python scripts/build_examples.py`, and brand assets with `python scripts/build_brand.py`.
2. Build the frontend with `npm --prefix web run build`.
3. Run `python scripts/promo_server.py` on its reserved isolated port `18089`.
4. Provide Playwright in the Node environment and run `node scripts/capture_promo.cjs`. It uses a fresh browser profile and Microsoft Edge by default; set `LEAFLOOM_BROWSER_CHANNEL=chrome` to use Chrome. No logged-in browser profile is used.
5. Review the 24 images under `assets/screenshots/{en,zh-CN,ja}/`. Runtime paths are replaced in the fixture's page before capture. Original screenshots are not painted over afterward.
6. Run `node scripts/record_promo.cjs` to record the English product walkthrough. It types a note, searches its new content, opens the source, focuses and pans the graph, previews a fictional AI suggestion and accepts it into a manual draft, then saves a folder scope. Only the fixture's copy of the example note is reset. The real user service is never used.
7. Run `python scripts/build_promo.py` with Pillow and NumPy installed, and FFmpeg/ffprobe on PATH. It composes the actual recordings into a 35-second English MP4 with directed camera moves, chapter titles, subtitles and an original 120-BPM score. Music contains synthesized instruments and action ticks, with no stock samples or voiceover.

The scripts never accept the normal service port. Demo files and state are temporary, and no full model download or AI login is needed. Stop the fixture after production.

## Storyboard

| Time | Scene | Message |
| --- | --- | --- |
| 0–2.5s | Brand | Your knowledge. Your deployment. Your control. |
| 2.5–9s | Write → read | Capture an idea. Keep your original files. |
| 9–16s | Type → search → open | Find the evidence. Open the source. |
| 16–23s | Select → explore → zoom → pan | Focus a note. Explore its connections. |
| 23–28.5s | Preview → accept into a draft | Optional AI. Review before you save. |
| 28.5–32s | Choose folders → save scope | Your deployment. Your files. Your search scope. |
| 32–35s | Brand closing | LeafLoom · Make it yours. · Open source · MIT |

Only the English video is produced, as requested. The application, guides and screenshot sets remain trilingual. Captions are burned in for playback without subtitle support; an SRT is supplied separately.

Each product scene makes one eased 0.6-second push toward a fixed anchor, then locks its zoom and crop for the remaining scene. There is no continuing camera pan, reframing or breathing zoom. Wider locked crops keep the operation buttons and draft banner visible. Brand cards and chapter text stay stationary, with only opacity transitions. The cursor and click ripples are presentation overlays attached to actual browser events. Cross-dissolves last 0.3 seconds. The AI scene retains an explicit fictional-demo label and stops at the unsaved-draft stage. No live AI generation is implied.

Reusable sources are in `assets/promo/recordings/`: five WebM takes and `take.json` with frame-aligned scene ranges and actual action times. `storyboard.json` records the edit and camera keyframes; `soundtrack.wav`, the SRT and the cover can be reused separately. A two-pixel recording timing mark is excluded from the final composition. The editor verifies H.264/AAC, 1920×1080, 30 fps and 35 seconds. Audio is normalized to a target of −16 LUFS with a −1.5 dBTP ceiling.

## 中文

24 张截图分别覆盖三语欢迎页、首页、阅读、检索、图谱、AI 和检索范围设置，另各有一张移动端截图。使用独立端口、临时配置和虚构资料；AI 禁止外部调用，演示回答明确标注。截图前在页面中隐藏环境路径。视频统一英文，35 秒横版，以真实输入、检索、打开来源、图谱聚焦与拖动、AI 草稿审阅和目录范围选择串联。每段只在开头推近一次，0.6 秒后固定镜头；品牌卡和章节标题保持静止。保留点击提示、转场和原创节拍音乐，无旁白。

## 日本語

3 言語のウェルカム、ホーム、閲覧、検索、グラフ、AI、検索範囲と、各言語のモバイル画面で計 24 枚です。独立したポートと一時設定、架空の資料を使い、AI の外部呼び出しを無効にします。環境パスを画面上で隠してから撮影します。動画は英語のみ、横向き 35 秒。実際の入力、検索、原文表示、グラフ操作、AI の変更確認、検索範囲の保存を収録しています。各シーンの冒頭で一度だけズームし、0.6 秒後はカメラを固定します。ブランドカードと章タイトルも固定し、クリック表示、トランジション、オリジナルのリズム音楽を加えています。ナレーションはありません。
