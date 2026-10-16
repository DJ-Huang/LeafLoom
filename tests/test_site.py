"""Public website contracts, without desktop dependencies or network access."""
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import tempfile
import unittest
from urllib.parse import unquote, urlsplit
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
            self.assertEqual(urls, [site.DEFAULT_URL + route for _, route, _ in site.LANGUAGES.values()])

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

    def test_template_rejects_missing_values(self):
        with self.assertRaisesRegex(ValueError, "Missing template value"):
            site.render("<h1>{{missing}}</h1>", {})


if __name__ == "__main__":
    unittest.main()
