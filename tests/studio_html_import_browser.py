"""Focused authored-HTML capture and replay regressions.

Run explicitly with ``python tests/studio_html_import_browser.py``; needs an
installed Chromium browser. All source pages/assets are disposable route data.
"""
from __future__ import annotations

import json
from pathlib import Path
import struct
from urllib.parse import urlparse
import unittest

import studio_runtime_browser as runtime_tests


LAYOUT = """root => {
  const bounds=root.getBoundingClientRect();
  return Object.fromEntries(['.copy','em','img'].map(selector=>{
    const element=root.querySelector(selector),rect=element.getBoundingClientRect(),style=getComputedStyle(element);
    return [selector,{x:rect.x-bounds.x,y:rect.y-bounds.y,width:rect.width,height:rect.height,color:style.color,font:style.font,fontWeight:style.fontWeight,display:style.display}];
  }).concat([['root',{width:bounds.width,height:bounds.height,background:getComputedStyle(root).backgroundColor}]]));
}"""


class HtmlImportBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = runtime_tests.StudioRuntimeBrowserTests()
        cls.fixture.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass()

    def setUp(self):
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def capture(self, markup, resources=None, evidence=None):
        boards = [{"id": "home", "name": "Home", "width": 800, "height": 600}]
        host = '<script>addEventListener("message",e=>{if(e.data.type==="studio-capture-ready")canvas.contentWindow.postMessage({type:"studio-capture-init",session:"capture",boards:' + json.dumps(boards) + ',entry:"Design/UI/Site/screen.html"},"https://studio.test");if(e.data.type==="studio-capture-complete")captured=e.data.pages;if(e.data.type==="studio-capture-error")captureError=e.data.message;});</script><iframe id="canvas" src="https://studio.test/Design/studio/capture.html?session=capture&parentOrigin=https%3A%2F%2Fparent.test"></iframe>'
        context = self.fixture.browser.new_context()
        def route(request):
            url = urlparse(request.request.url)
            if url.hostname == "parent.test":
                request.fulfill(body=host, content_type="text/html")
            elif url.path.endswith("capture.js") or url.path.endswith("capture.html"):
                request.fulfill(body=(runtime_tests.RUNTIME / url.path.rsplit("/", 1)[1]).read_text(), content_type="text/javascript" if url.path.endswith(".js") else "text/html")
            elif url.path.endswith("screen.html"):
                request.fulfill(body=markup, content_type="text/html")
            elif request.request.url in (resources or {}):
                resource = resources[request.request.url]
                request.fulfill(**resource if isinstance(resource, dict) else {"body": resource, "content_type": "text/css"})
            else:
                request.fulfill(body="", status=404)
        context.route("**/*", route)
        page = context.new_page()
        try:
            page.goto("https://parent.test/")
            page.wait_for_function("window.captured||window.captureError")
            self.assertIsNone(page.evaluate("window.captureError"))
            captured = page.evaluate("window.captured")
            if evidence:
                original = context.new_page()
                original.set_viewport_size({"width": 800, "height": 600})
                original.goto("https://studio.test/Design/UI/Site/screen.html?id=home")
                original.evaluate("()=>Promise.all([document.fonts.ready,...[...document.images].map(image=>image.decode())])")
                self.original_layout = original.locator("#artboard").evaluate(LAYOUT)
                self.original_png = original.locator("#artboard").screenshot(path=str(evidence / "html-import-original.png"), animations="disabled")
            return captured
        finally:
            context.close()

    def test_document_context_mixed_native_text_and_selector_isolation(self):
        pages = self.capture('''<!doctype html><html class="dark" lang="ja" dir="rtl"><head><style>
            :root { --ink: rgb(12, 34, 56); }
            html.dark body.theme { font-family: monospace; margin: 13px; }
            html.dark > body.theme > main.host #artboard { padding: 17px; }
            :is(html.dark) body .label { color: var(--ink); }
            .label > :first-child { border-left: 3px solid red; }
            [title="body"] { letter-spacing: 2px; }
            div { padding: 41px; }
            .specificity {color:red;} body span {color:blue;}
            :root {--specificity:rgb(120,10,20);} html {--specificity:rgb(20,20,120);}
            .pseudo-specificity {color:var(--specificity);}
            </style></head><body class="theme" data-theme="night">
            <main class="host"><section id="artboard"><p class="label" title="body"> Hello <em>world</em> ! </p><span class="specificity">Class wins</span><span class="pseudo-specificity">Root wins</span></section></main>
            </body></html>''')
        captured = pages[0]
        self.assertEqual(captured["authoredContext"]["html"]["attributes"]["lang"], "ja")
        self.assertEqual(captured["authoredContext"]["html"]["attributes"]["dir"], "rtl")
        self.assertEqual(captured["authoredContext"]["ancestors"][0]["tag"], "main")
        text = captured["nodes"][0]["children"][0]["children"]
        self.assertTrue(text[0]["props"]["textNode"])
        self.assertEqual(text[0]["props"]["text"], " Hello ")
        self.fixture.mount([], pages=pages)
        page = self.fixture.page
        label = page.locator("p.label")
        self.assertEqual(label.evaluate("el=>[...el.childNodes].map(node=>node.nodeType)"), [3, 1, 3])
        self.assertEqual(label.evaluate("el=>getComputedStyle(el).color"), "rgb(12, 34, 56)")
        self.assertEqual(label.evaluate("el=>getComputedStyle(el).fontFamily"), "monospace")
        self.assertEqual(label.evaluate("el=>getComputedStyle(el).direction"), "rtl")
        self.assertEqual(label.evaluate("el=>getComputedStyle(el).letterSpacing"), "2px")
        self.assertEqual(page.locator("section.studio-authored").evaluate("el=>getComputedStyle(el).padding"), "17px")
        self.assertEqual(label.locator("em").evaluate("el=>getComputedStyle(el).borderLeftWidth"), "3px")
        self.assertEqual(page.locator("[data-studio-document-root=body]").evaluate("el=>getComputedStyle(el).margin"), "13px")
        self.assertEqual(page.locator("[data-studio-document-root=body]").evaluate("el=>getComputedStyle(el).padding"), "0px")
        self.assertNotEqual(page.locator("[data-studio-document-root=html]").evaluate("el=>el.localName"), "div")
        self.assertEqual(page.locator(".specificity").evaluate("el=>getComputedStyle(el).color"), "rgb(255, 0, 0)")
        self.assertEqual(page.locator(".pseudo-specificity").evaluate("el=>getComputedStyle(el).color"), "rgb(120, 10, 20)")
        self.assertNotEqual(page.locator("body").evaluate("el=>getComputedStyle(el).fontFamily"), "monospace")
        # Updating a native text layer keeps both its DOM identity and siblings.
        page.evaluate("""() => {
          window.nativeText=document.querySelector('p.label').firstChild;
          const model=instance.document;
          model.pages[0].nodes[0].children[0].children[0].props.text='Changed ';
          window.reused=instance.update(model,{mode:'edit'});
        }""")
        self.assertTrue(page.evaluate("window.reused"))
        self.assertTrue(page.evaluate("nativeText===document.querySelector('p.label').firstChild"))
        self.assertEqual(label.text_content(), "Changed world ! ")
        self.assertEqual(page.evaluate("events.filter(e=>e.type==='studio-error')"), [])

    def test_base_responsive_sources_media_imports_and_unreadable_stylesheets(self):
        data = "data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%3E%3C/svg%3E"
        pages = self.capture('''<!doctype html><html><head><base href="/theme/">
            <link rel="stylesheet" href="screen.css" media="screen">
            <link rel="stylesheet" href="https://remote.test/private.css">
            <style media="print">.label{color:red}</style>
            <style id="disabled">.label{display:none}</style>
            </head><body><main id="artboard"><p class="label">Visible</p><picture>
            <source media="(min-width:600px)" srcset="wide.png 1x, wide@2x.png 2x">
            <img src="fallback.png" srcset="''' + data + ''' 1x, high.png 2x" sizes="100vw">
            </picture></main><script>document.querySelector('#disabled').sheet.disabled=true</script></body></html>''', {
                "https://studio.test/theme/screen.css": '@import "nested/colors.css" screen; .label{font-size:21px}',
                "https://studio.test/theme/nested/colors.css": '.label{color:rgb(10,20,30);background-image:url("../texture.png")}',
                "https://remote.test/private.css": 'body{background:red}',
            })
        captured = pages[0]
        picture = next(node for node in captured["nodes"][0]["children"] if node["props"]["tag"] == "picture")
        children = [node for node in picture["children"] if not node["props"].get("textNode")]
        self.assertEqual(children[0]["props"]["attributes"]["srcset"], "__STUDIO_ASSET__/theme/wide.png 1x, __STUDIO_ASSET__/theme/wide@2x.png 2x")
        self.assertEqual(children[1]["props"]["attributes"]["srcset"], data + " 1x, __STUDIO_ASSET__/theme/high.png 2x")
        self.assertEqual(children[1]["props"]["src"], "__STUDIO_ASSET__/theme/fallback.png")
        self.assertIn("__STUDIO_ASSET__/theme/texture.png", captured["css"])
        self.assertIn("@media print", captured["css"])
        self.assertNotIn("display: none", captured["css"])
        self.assertNotIn("@import", captured["css"])
        self.assertEqual(captured["migration"]["unavailableStylesheets"], ["https://remote.test/private.css"])
        self.fixture.mount([], pages=pages)
        label = self.fixture.page.locator("p.label")
        self.assertEqual(label.evaluate("el=>getComputedStyle(el).color"), "rgb(10, 20, 30)")
        self.assertEqual(label.evaluate("el=>getComputedStyle(el).fontSize"), "21px")
        self.assertEqual(self.fixture.page.locator("img").get_attribute("srcset"), data + " 1x, file:///studio-export/theme/high.png 2x")

    def test_body_fallback_has_one_body_context_and_no_active_source_tags(self):
        pages = self.capture('''<!doctype html><html lang="en"><head><style>body.theme > p{color:rgb(3,4,5)}</style></head>
            <body class="theme" onload="window.loaded=true"><p>Hello</p><script>window.original=true</script></body></html>''')
        self.assertEqual(pages[0]["authoredContext"]["root"], "body")
        self.assertNotIn("onload", pages[0]["authoredContext"]["body"]["attributes"])
        self.assertEqual([node["props"].get("tag") for node in pages[0]["nodes"] if not node["props"].get("textNode")], ["p"])
        self.fixture.mount([], pages=pages)
        self.assertEqual(self.fixture.page.locator("[data-studio-document-root=body]").count(), 1)
        self.assertEqual(self.fixture.page.locator("p").evaluate("el=>getComputedStyle(el).color"), "rgb(3, 4, 5)")

    def test_original_and_imported_layout_with_visual_evidence(self):
        evidence = Path(__file__).resolve().parents[1] / ".cache/studio-qa"
        evidence.mkdir(parents=True, exist_ok=True)
        artwork = '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="64"><rect width="96" height="64" fill="#2467a8"/><circle cx="48" cy="32" r="21" fill="#ffcc55"/></svg>'
        resources = {"https://studio.test/theme/" + name: {"body": artwork, "content_type": "image/svg+xml"} for name in ("small.svg", "wide.svg", "large.svg")}
        markup = '''<!doctype html><html class="original"><head><base href="/theme/"><style>
            :root { --surface:#edf3fd; }
            html.original body.theme {font-family:Arial,sans-serif;font-size:16px;color:#163555;margin:13px;}
            body.theme > main.host {padding:11px;}
            html.original body.theme main.host #artboard {width:360px;padding:20px;border:2px solid #2467a8;box-sizing:border-box;background:var(--surface);}
            #artboard .copy {margin:0 0 12px;line-height:24px;}
            .copy > :first-child {font-weight:700;color:#924500;}
            #artboard img {width:96px;height:64px;display:block;}
            div {padding:37px;}
            </style></head><body class="theme"><main class="host"><section id="artboard" class="original-artboard"><p class="copy">Hello <em>mixed</em> text.</p><picture><source media="(min-width:600px)" srcset="wide.svg 1x, large.svg 2x"><img src="small.svg" width="96" height="64" alt="Blue and gold illustration"></picture></section></main></body></html>'''
        pages = self.capture(markup, resources, evidence=evidence)
        page = self.fixture.page
        def image_route(request):
            resource = resources.get(request.request.url)
            request.fulfill(**resource) if resource else request.fulfill(body="", status=404)
        page.context.route("https://studio.test/**", image_route)
        page.evaluate("""pages=>{
          window.events=[];
          window.instance=LeafLoomStudio.mount(document.getElementById('studio-root'),{schemaVersion:1,id:'comparison',pages,assets:{},scripts:{},components:{}},{mode:'edit',assetBase:'https://studio.test/',onMessage:event=>events.push(event)});
          instance.setZoom(1);
        }""", pages)
        page.evaluate("()=>Promise.all([document.fonts.ready,...[...document.images].map(image=>image.decode())])")
        imported = page.locator(".original-artboard")
        actual = imported.evaluate(LAYOUT)
        imported_png = imported.screenshot(path=str(evidence / "html-import-converted.png"), animations="disabled")
        (evidence / "html-import-layout.json").write_text(json.dumps({"original": self.original_layout, "imported": actual}, indent=2))
        # Physical screenshot dimensions and subpixel box positions must match;
        # the two PNGs are uploaded by CI for a direct visual comparison.
        self.assertEqual(struct.unpack('>II', self.original_png[16:24]), struct.unpack('>II', imported_png[16:24]))
        for selector, expected in self.original_layout.items():
            for key, value in expected.items():
                with self.subTest(selector=selector, property=key):
                    if isinstance(value, (int, float)):
                        self.assertAlmostEqual(actual[selector][key], value, delta=.25)
                    else:
                        self.assertEqual(actual[selector][key], value)
        self.assertEqual(page.locator("img").evaluate("el=>el.currentSrc"), "https://studio.test/theme/wide.svg")
        self.assertEqual(page.evaluate("events.filter(e=>e.type==='studio-error')"), [])


    def test_html_edit_export_reopen_uses_the_portable_renderer(self):
        """A real ZIP, not just a second mount of the in-memory import."""
        import copy
        import mimetypes
        import shutil
        import zipfile
        from unittest.mock import patch
        from test_design_workspace import DesignWorkspaceTests

        pages = self.capture('''<!doctype html><html><head><style>
          #artboard{width:360px;padding:24px;box-sizing:border-box;background:#eef3fa}
          h1{font:700 28px/1.3 Arial;margin:0 0 12px}p{font:16px/1.5 Arial;margin:0}
          </style></head><body><section id="artboard"><h1>A studio story</h1><p>Original copy</p></section>
          <script>window.originalOnly = true</script></body></html>''')
        page = self.fixture.page
        self.fixture.mount([], pages=pages)
        nodes = pages[0]["nodes"]
        def walk(items):
            for item in items:
                yield item
                yield from walk(item.get("children", []))
        heading = next(item for item in walk(nodes) if item.get("props", {}).get("tag") == "h1")
        changed = copy.deepcopy(pages)
        target = next(item for item in walk(changed[0]["nodes"]) if item["id"] == heading["id"])
        target["props"]["text"] = "An edited brand story with a longer heading"
        target["style"].update({"color":"#3355aa", "letterSpacing":0.5})
        page.evaluate("pages=>{const doc=instance.document;doc.pages=pages;instance.update(doc,{mode:'edit'});instance.setZoom(1);}", changed)
        edited = page.locator("h1.studio-authored")
        expected = edited.evaluate("el=>({text:el.textContent,color:getComputedStyle(el).color,width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height})")
        self.assertEqual(expected["text"], target["props"]["text"])
        fixture = DesignWorkspaceTests()
        fixture.setUp()
        context = None
        try:
            document = fixture.project["document"]
            document["pages"] = changed
            fixture.docs.apply(fixture.directory, [{"type":"document.replace", "document":document}], fixture.project["revision"], "import-edit", "Import and edit HTML")
            with patch.object(fixture.workspace, "session", return_value={"origin":"http://localhost:1000", "id":"export-fixture"}):
                exported = fixture.workspace.export(fixture.directory)
            evidence = Path(__file__).resolve().parents[1] / ".cache/studio-qa"
            evidence.mkdir(parents=True, exist_ok=True)
            bundle = fixture.root / exported["path"]
            shutil.copyfile(bundle, evidence / "polish-import-edited.zip")
            with zipfile.ZipFile(bundle) as archive:
                files = {name:archive.read(name) for name in archive.namelist()}
            context = self.fixture.browser.new_context(viewport={"width":800,"height":600})
            def serve(route):
                name = urlparse(route.request.url).path.lstrip('/') or 'index.html'
                if name not in files:
                    route.fulfill(status=404,body='missing')
                else:
                    route.fulfill(body=files[name], content_type=mimetypes.guess_type(name)[0] or 'application/octet-stream')
            context.route('https://export.test/**', serve)
            exported_page = context.new_page()
            exported_page.goto('https://export.test/index.html')
            actual = exported_page.locator('h1.studio-authored')
            actual.wait_for()
            exported_page.evaluate('LeafLoomStudioInstance.setZoom(1)')
            actual_values = actual.evaluate("el=>({text:el.textContent,color:getComputedStyle(el).color,width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height})")
            self.assertEqual(actual_values, expected)
            self.assertIsNone(exported_page.evaluate('window.originalOnly'))
            exported_page.screenshot(path=str(evidence / 'polish-html-export-reopened.png'))
            (evidence / 'polish-html-roundtrip.json').write_text(json.dumps({"edited":expected,"exported":actual_values},indent=2))
        finally:
            if context:
                context.close()
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
