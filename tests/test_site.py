"""Public website contracts, without desktop dependencies or network access."""
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import tempfile
import unittest
from urllib.parse import unquote, urlsplit
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts/build_site.py")
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)


def fixture():
    names = ("LeafLoom-1.2.3-windows-x64-setup.exe", "LeafLoom-1.2.3-macos-arm64.dmg", "SHA256SUMS.txt", "SHA256SUMS-windows.txt")
    return {"tag_name": "v1.2.3", "draft": False, "prerelease": False,
            "assets": [{"name": name, "browser_download_url": f"{site.REPO}/releases/download/v1.2.3/{name}", "size": 100_000_000} for name in names]}


class Page(HTMLParser):
    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.references = []
        self.language = None
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "html":
            self.language = attrs.get("lang")
        for key in ("href", "src"):
            if key in attrs:
                self.references.append(attrs[key])


class WebsiteTests(unittest.TestCase):
    def test_three_languages_links_assets_and_release_downloads(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            site.build(output, fixture())
            for lang, (_, route, _) in site.LANGUAGES.items():
                content = (output / route / "index.html").read_text(encoding="utf-8")
                page = Page(content)
                self.assertEqual(page.language, lang)
                self.assertNotIn("{{", content)
                self.assertIn(f"/LeafLoom/assets/{lang}/showcase-markdown.png", content)
                self.assertIn("LeafLoom-1.2.3-windows-x64-setup.exe", content)
                self.assertIn("LeafLoom-1.2.3-macos-arm64.dmg", content)
                self.assertIn('aria-current="page"', content)
                for reference in page.references:
                    parsed = urlsplit(reference)
                    if parsed.scheme or parsed.netloc:
                        continue
                    if parsed.path:
                        self.assertTrue(parsed.path.startswith("/LeafLoom/"), reference)
                        target = output / unquote(parsed.path.removeprefix("/LeafLoom/"))
                        self.assertTrue(target.exists(), reference)
                        if target.is_dir():
                            self.assertTrue((target / "index.html").is_file(), reference)
                    elif parsed.fragment:
                        self.assertIn(parsed.fragment, page.ids)
            tree = ET.parse(output / "sitemap.xml")
            urls = [node.text for node in tree.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
            self.assertEqual(urls, [site.DEFAULT_URL + page for _, route, _ in site.LANGUAGES.values() for page in (route, route + "about/")])

    def test_missing_platform_does_not_offer_another_versions_installer(self):
        release = fixture()
        release["assets"] = [asset for asset in release["assets"] if not asset["name"].endswith(".dmg")]
        with tempfile.TemporaryDirectory() as temp:
            site.build(Path(temp), release, "https://example.com/")
            content = (Path(temp) / "index.html").read_text(encoding="utf-8")
            self.assertNotIn(".dmg", content)
            self.assertIn('aria-disabled="true"', content)
            self.assertIn("All releases", content)
            self.assertIn('href="/zh-CN/"', content)

    def test_rejects_nonpublic_release_and_foreign_download(self):
        for field in ("draft", "prerelease"):
            release = fixture()
            release[field] = True
            with self.assertRaises(ValueError):
                site.release_info(release)
        release = fixture()
        release["assets"][0]["browser_download_url"] = "https://example.com/untrusted.exe"
        with self.assertRaises(ValueError):
            site.release_info(release)

    def test_platform_fallback_uses_newest_stable_version_and_matching_checksum(self):
        release = fixture()
        release["assets"] = [asset for asset in release["assets"] if not asset["name"].endswith(".dmg")]

        def older(tag):
            candidate = fixture()
            candidate["tag_name"] = tag
            for asset in candidate["assets"]:
                asset["name"] = asset["name"].replace("1.2.3", tag[1:])
                asset["browser_download_url"] = asset["browser_download_url"].replace("1.2.3", tag[1:])
            return candidate

        preview = older("v1.2.2")
        preview["prerelease"] = True
        draft = older("v1.2.2")
        draft["draft"] = True
        release["fallback_releases"] = [older("v1.1.9"), preview, draft, older("v1.2.1"), older("v1.2.0"), older("v2.0.0")]
        with tempfile.TemporaryDirectory() as temp:
            site.build(Path(temp), release)
            for _, route, _ in site.LANGUAGES.values():
                content = (Path(temp) / route / "index.html").read_text(encoding="utf-8")
                self.assertIn("v1.2.3/LeafLoom-1.2.3-windows-x64-setup.exe", content)
                self.assertIn("v1.2.1/LeafLoom-1.2.1-macos-arm64.dmg", content)
                self.assertIn("v1.2.1/SHA256SUMS.txt", content)
                self.assertIn("v1.2.3/SHA256SUMS-windows.txt", content)
                self.assertIn('releases/tag/v1.2.1">v1.2.1</a>', content)
                self.assertNotIn('aria-disabled="true"', content)
                self.assertNotIn("v1.2.2", content)
                self.assertNotIn("v1.1.9", content)

    def test_history_fetch_paginates_and_skips_history_for_complete_release(self):
        release = fixture()
        with patch.object(site, "release_json", return_value=release) as fetch:
            self.assertEqual(site.latest_release(), release)
            fetch.assert_called_once_with("releases/latest")
        release["assets"] = []
        with patch.object(site, "release_json", side_effect=[release, [release] * 100, [fixture()]]) as fetch:
            result = site.latest_release()
            self.assertEqual(len(result["fallback_releases"]), 101)
            self.assertEqual(fetch.call_args_list[-1].args, ("releases?per_page=100&page=2",))

    def test_template_rejects_missing_values(self):
        with self.assertRaisesRegex(ValueError, "Missing template value"):
            site.render("<h1>{{missing}}</h1>", {})


if __name__ == "__main__":
    unittest.main()
