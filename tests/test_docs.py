"""Static documentation coverage, safe rendering and deployed-prefix link contracts."""
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import unquote, urlsplit
from unittest.mock import patch

from scripts.build_docs import Documentation, LANGUAGES, SECTIONS, safe_url

ROOT = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids = []
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        for name in ("href", "src"):
            if name in attrs:
                self.links.append(attrs[name])


class DocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temp.name)
        cls.docs = Documentation("https://example.com/LeafLoom/")
        cls.urls = cls.docs.build(cls.output)
        # The main website owns these routes/assets; avoid rebuilding its video.
        for route in ("", "zh-CN", "ja"):
            folder = cls.output / route
            folder.mkdir(exist_ok=True)
            (folder / "index.html").write_text('<div id="download"></div>')
        (cls.output / "assets").mkdir()
        (cls.output / "assets/logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_every_article_is_localized_and_has_task_structure(self):
        self.assertEqual(len(self.docs.slugs), 43)
        self.assertEqual(len(self.urls), 132)
        for lang in LANGUAGES:
            index = json.loads((self.output / "docs" / lang / "search.json").read_text())
            self.assertEqual(len(index["articles"]), len(self.docs.slugs))
            for article in index["articles"]:
                self.assertTrue(article["summary"], article["slug"])
                self.assertGreater(len(article["text"]), len(article["summary"]))
                if article["slug"] in self.docs.navigation["sources"]:
                    continue
                source = self.docs.articles[lang, article["slug"]]
                self.assertEqual([item["id"] for item in source["toc"]], list(SECTIONS))
            self.assertTrue(any("annotations.sqlite" in article["text"] for article in index["articles"]))

    def test_all_rendered_links_assets_and_cross_page_fragments_resolve(self):
        pages = {path: Page(path.read_text()) for path in self.output.rglob("*.html")}
        for path, page in pages.items():
            self.assertEqual(len(page.ids), len(set(page.ids)), path)
            for link in page.links:
                parsed = urlsplit(link)
                if parsed.scheme or parsed.netloc:
                    continue
                if parsed.path:
                    self.assertTrue(parsed.path.startswith("/LeafLoom/"), (path, link))
                    target = self.output / unquote(parsed.path.removeprefix("/LeafLoom/"))
                    if target.is_dir():
                        target /= "index.html"
                else:
                    target = path
                self.assertTrue(target.is_file(), (path, link))
                if parsed.fragment:
                    self.assertIn(unquote(parsed.fragment), pages[target].ids, (path, link))

    def test_release_notes_route_points_to_published_v016(self):
        self.assertEqual(
            self.docs.navigation["sources"]["release-notes"],
            "docs/{lang}/RELEASE_NOTES_0.1.6.md",
        )
        for lang in LANGUAGES:
            article = self.docs.articles[lang, "release-notes"]
            self.assertIn("LeafLoom 0.1.6", article["title"])
            html = (self.output / "docs" / lang / "release-notes/index.html").read_text()
            self.assertIn(f"docs/{lang}/RELEASE_NOTES_0.1.6.md", html)
            for version in ("0.1.3", "0.1.4", "0.1.5"):
                self.assertTrue((ROOT / "docs" / lang / f"RELEASE_NOTES_{version}.md").is_file())

    def test_custom_prefix_and_language_links_retain_article(self):
        docs = Documentation("https://example.com/custom/prefix/")
        self.assertEqual(docs.route("ja", "editing"), "/custom/prefix/docs/ja/editing/")
        html = (self.output / "docs/zh-CN/editing/index.html").read_text()
        self.assertIn('href="/LeafLoom/docs/ja/editing/"', html)
        self.assertIn('href="/LeafLoom/docs/en/editing/"', html)
        self.assertIn('id="steps"', html)
        self.assertNotIn("{{", html)

    def test_renderer_escapes_html_and_rejects_private_or_external_images(self):
        source = ROOT / "docs/en/help/editing.md"
        markdown = '# Safe title\n\n' + '\n\n'.join(f'## {section}\n\n<script>alert(1)</script>' for section in SECTIONS)
        with patch.object(Path, 'read_text', return_value=markdown):
            rendered = self.docs.read_article(source)["html"]
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;script&gt;', rendered)
        for link in ("javascript:alert(1)", "//evil.example/pixel.png", "data:text/html,test", "https://example.com/line\nbreak"):
            with self.assertRaises(ValueError, msg=link):
                safe_url(link)
        for link in ("https://example.com/pixel.png", "../../../.env", "../../../pyproject.toml", "../../../../outside.png"):
            with self.assertRaises(ValueError, msg=link):
                self.docs.resolve_link(link, source, image=True)

    def test_pages_workflow_rebuilds_authored_documentation(self):
        workflow = (ROOT / ".github/workflows/pages.yml").read_text()
        self.assertEqual(workflow.count("- 'docs/**'"), 2)
        self.assertIn("pip install -r site/requirements.txt", workflow)
        self.assertIn("-p test_docs.py", workflow)


if __name__ == "__main__":
    unittest.main()
