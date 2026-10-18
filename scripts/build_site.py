"""Build the independent public site using compiled catalogs and public Release assets."""
from __future__ import annotations

import argparse
from html import escape
import json
import os
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/DJ-Huang/LeafLoom"
DEFAULT_URL = "https://dj-huang.github.io/LeafLoom/"
LANGUAGES = {"en": ("English", "", "en_US"), "zh-CN": ("中文", "zh-CN/", "zh_CN"), "ja": ("日本語", "ja/", "ja_JP")}
SHOTS = ("showcase-markdown", "showcase-graph", "showcase-html", "04-search", "showcase-ai")


def release_json(path: str):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "LeafLoom-pages"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(f"https://api.github.com/repos/DJ-Huang/LeafLoom/{path}", headers=headers), timeout=30) as response:
        return json.load(response)


def stable_version(tag: str) -> tuple[int, int, int, int]:
    if not re.fullmatch(r"v?\d+\.\d+\.\d+(?:\.\d+)?", tag):
        raise ValueError(f"Unsupported stable release tag: {tag}")
    parts = tuple(map(int, tag.removeprefix("v").split(".")))
    return parts + (0,) * (4 - len(parts))


def latest_release(expected_tag: str = "") -> dict:
    # GitHub can dispatch 'published' before releases/latest reflects that tag.
    # Fail instead of deploying stale HTML if the API never catches up.
    expected = stable_version(expected_tag) if expected_tag else None
    for attempt in range(6 if expected else 1):
        release = release_json("releases/latest")
        if expected is None or stable_version(release["tag_name"]) >= expected:
            break
        if attempt < 5:
            time.sleep(5)
    else:
        raise RuntimeError(
            f"GitHub releases/latest is still {release['tag_name']}; "
            f"expected at least published {expected_tag}. Refusing a stale Pages deployment."
        )
    info = release_info(release)
    if all(info[platform] for platform in ("windows", "macos")):
        return release
    # The API paginates by creation date, not version. Inspect the full history
    # before selecting the newest available stable installer for each platform.
    history = []
    page = 1
    while True:
        batch = release_json(f"releases?per_page=100&page={page}")
        history.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return {**release, "fallback_releases": history}


def release_info(release: dict) -> dict:
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("The public site requires a published stable Release")
    tag = release["tag_name"]
    if not re.fullmatch(r"v?\d+\.\d+\.\d+(?:\.\d+)?", tag):
        raise ValueError("Unsupported stable release tag")
    assets = {}
    for asset in release.get("assets", []):
        url = asset["browser_download_url"]
        if not url.startswith(f"{REPO}/releases/download/{tag}/"):
            raise ValueError("Release assets must be hosted by the public repository")
        assets[asset["name"]] = asset
    version = tag.removeprefix("v")
    return {
        "tag": tag, "url": f"{REPO}/releases/tag/{tag}", "assets": assets,
        "windows": assets.get(f"LeafLoom-{version}-windows-x64-setup.exe"),
        "macos": assets.get(f"LeafLoom-{version}-macos-arm64.dmg"),
    }


def platform_releases(release: dict) -> dict:
    latest = release_info(release)

    history = []
    for candidate in release.get("fallback_releases", []):
        tag = candidate.get("tag_name", "")
        if candidate.get("draft") or candidate.get("prerelease") or not re.fullmatch(r"v?\d+\.\d+\.\d+(?:\.\d+)?", tag):
            continue
        if stable_version(tag) < stable_version(latest["tag"]):
            history.append(release_info(candidate))
    candidates = [latest] + sorted(history, key=lambda item: stable_version(item["tag"]), reverse=True)
    return {platform: next((item for item in candidates if item[platform]), latest)
            for platform in ("windows", "macos")}


def render(template: str, values: dict) -> str:
    def substitute(match):
        key = match.group(1)
        if key not in values:
            raise ValueError(f"Missing template value: {key}")
        return values[key]
    return re.sub(r"\{\{(\w+)\}\}", substitute, template)


def build(output: Path, release: dict, base_url: str = DEFAULT_URL) -> None:
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("base-url must be an absolute website URL without query or fragment")
    base_url = base_url.rstrip("/") + "/"
    base = urlsplit(base_url).path
    info = release_info(release)
    downloads = platform_releases(release)
    template = (ROOT / "site/page.html").read_text(encoding="utf-8")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "site/style.css", output / "style.css")
    assets_dir = output / "assets"
    assets_dir.mkdir(exist_ok=True)
    shutil.copy2(ROOT / "assets/brand/logo.svg", assets_dir / "logo.svg")
    shutil.copy2(ROOT / "assets/promo/cover.png", assets_dir / "cover.png")
    shutil.copy2(ROOT / "assets/promo/leafloom-en.mp4", assets_dir / "leafloom-en.mp4")
    for lang, (_, route, og_locale) in LANGUAGES.items():
        catalog = json.loads((ROOT / f"vault_rag/locales/{lang}.json").read_text(encoding="utf-8"))
        values = {key.removeprefix("site."): escape(text, quote=True) for key, text in catalog.items() if key.startswith("site.")}

        def t(key):
            try:
                return values[key]
            except KeyError:
                raise ValueError(f"Missing {lang} translation: site.{key}") from None

        guide_path = f"docs/{lang}/GUIDE.md"
        guide_url = f"{REPO}/blob/main/{guide_path}"
        language_links = []
        alternates = []
        for other, (label, other_route, _) in LANGUAGES.items():
            current = ' aria-current="page"' if other == lang else ""
            language_links.append(f'<a href="{escape(base + other_route)}" lang="{other}" hreflang="{other}"{current}>{label}</a>')
            alternates.append(f'<link rel="alternate" hreflang="{other}" href="{escape(base_url + other_route)}">')
        alternates.append(f'<link rel="alternate" hreflang="x-default" href="{escape(base_url)}">')

        def download_button(platform, secondary=False):
            asset = downloads[platform][platform]
            classes = "button secondary" if secondary else "button"
            if not asset:
                return f'<span class="button unavailable" aria-disabled="true">{t(platform)} · {t("unavailable")}</span>'
            return f'<a class="{classes}" href="{escape(asset["browser_download_url"])}">{t("download_" + platform)} <span aria-hidden="true">↓</span></a>'

        platforms = []
        for platform, requirement in (("windows", "Windows 10 / 11 · x64"), ("macos", "macOS 14+ · Apple Silicon")):
            platform_info = downloads[platform]
            asset = platform_info[platform]
            checksum_name = "SHA256SUMS-windows.txt" if platform == "windows" and "SHA256SUMS-windows.txt" in platform_info["assets"] else "SHA256SUMS.txt"
            checksum = platform_info["assets"].get(checksum_name)
            checksum_link = f'<a href="{escape(checksum["browser_download_url"])}">SHA-256 ↗</a>' if checksum and asset else ""
            size = f'{asset["size"] / (1024 * 1024):.0f} MB' if asset else t("unavailable")
            version_link = f'<a href="{escape(platform_info["url"])}">{escape(platform_info["tag"])}</a>' if asset else ""
            platforms.append(f'<article class="platform"><h3>{t(platform)}</h3><p>{requirement}</p>{download_button(platform)}<div class="platform-meta"><span>{version_link} · {size}</span>{checksum_link}</div></article>')

        features = []
        for number, key, shot in (("01", "markdown", "showcase-markdown"), ("02", "graph", "showcase-graph"), ("03", "html", "showcase-html"), ("04", "search", "04-search")):
            features.append(f'<article class="feature"><div class="feature-copy"><span class="feature-index">{number} /</span><h3>{t(key + "_title")}</h3><p>{t(key + "_body")}</p></div><figure><img src="{escape(base)}assets/{lang}/{shot}.png" width="1800" height="1125" loading="lazy" alt="{t(key + "_alt")}"></figure></article>')
        principles = "".join(f'<article><h3>{t(key + "_title")}</h3><p>{t(key + "_body")}</p></article>' for key in ("files", "scope", "optional"))
        values.update({
            "lang": lang, "og_locale": og_locale, "base": escape(base), "base_url": escape(base_url),
            "about_url": escape(base + route + "about/"),
            "home": escape(base + route), "canonical": escape(base_url + route),
            "language_links": "".join(language_links), "alternates": "\n  ".join(alternates),
            "guide_url": guide_url, "ai_url": f"{REPO}/blob/main/docs/{lang}/AI.md",
            "release_url": escape(info["url"]), "release_tag": escape(info["tag"]),
            "hero_downloads": download_button("windows") + download_button("macos", secondary=True),
            "platforms": "".join(platforms), "features": "\n".join(features), "principles": principles,
            "headline": t("headline").replace("\n", "<br>"),
        })
        folder = output / route
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "index.html").write_text(render(template, values), encoding="utf-8")
        about_values = dict(values)
        about_values.update({
            "title": t("about_title"), "description": t("about_intro"),
            "canonical": escape(base_url + route + "about/"),
            "language_links": "".join(
                f'<a href="{escape(base + other_route + "about/")}" lang="{other}" hreflang="{other}"' +
                (' aria-current="page"' if other == lang else '') + f'>{label}</a>'
                for other, (label, other_route, _) in LANGUAGES.items()),
            "alternates": "\n  ".join(
                f'<link rel="alternate" hreflang="{other}" href="{escape(base_url + other_route + "about/")}">'
                for other, (_, other_route, _) in LANGUAGES.items()) +
                f'\n  <link rel="alternate" hreflang="x-default" href="{escape(base_url + "about/")}">',
        })
        about_folder = folder / "about"
        about_folder.mkdir(exist_ok=True)
        (about_folder / "index.html").write_text(
            render((ROOT / "site/about.html").read_text(encoding="utf-8"), about_values), encoding="utf-8")
        target = assets_dir / lang
        target.mkdir(exist_ok=True)
        for shot in SHOTS:
            shutil.copy2(ROOT / f"assets/screenshots/{lang}/{shot}.png", target / f"{shot}.png")
    urls = "".join(f"<url><loc>{escape(base_url + route)}</loc></url>" for _, route, _ in LANGUAGES.values() for route in (route, route + "about/"))
    (output / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n', encoding="utf-8")
    (output / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base_url}sitemap.xml\n", encoding="utf-8")
    (output / ".nojekyll").touch()
    print(f"Built 3 languages for {info['tag']} in {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/site")
    parser.add_argument("--base-url", default=DEFAULT_URL)
    parser.add_argument("--release-json", type=Path, help="Use a saved public API response for offline checks")
    args = parser.parse_args()
    release = (json.loads(args.release_json.read_text(encoding="utf-8-sig")) if args.release_json
               else latest_release(os.environ.get("LEAFLOOM_PUBLISHED_TAG", "")))
    build(args.output, release, args.base_url)


if __name__ == "__main__":
    main()
