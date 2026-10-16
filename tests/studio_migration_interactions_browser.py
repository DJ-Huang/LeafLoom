"""Focused capture/runtime contracts for the reference prototype's two handlers.

Run explicitly: python tests/studio_migration_interactions_browser.py
The disposable markup mirrors data-target/data-source navigation and the
toggle/on/aria-checked contract; no real project is written or recaptured.
"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse
import unittest

import studio_runtime_browser as runtime_tests

RUNTIME = runtime_tests.RUNTIME


class MigrationInteractionTests(unittest.TestCase):
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

    def test_capture_adapts_switches_and_contextual_settings_return(self):
        boards = [{"id": item, "kind": item, "name": item, "width": 800, "height": 600} for item in ("home", "game", "pause", "settings", "help")]
        context = self.fixture.browser.new_context()
        capture_js = (RUNTIME / "capture.js").read_text()
        capture_html = (RUNTIME / "capture.html").read_text()
        host = '<script>window.captured=null;addEventListener("message",e=>{if(e.data.type==="studio-capture-ready")canvas.contentWindow.postMessage({type:"studio-capture-init",session:"capture",boards:' + json.dumps(boards) + ',entry:"Design/UI/Site/screen.html"},"https://studio.test");if(e.data.type==="studio-capture-complete")captured=e.data.pages;if(e.data.type==="studio-capture-error")captureError=e.data.message;});</script><iframe id="canvas" src="https://studio.test/Design/studio/capture.html?session=capture&parentOrigin=https%3A%2F%2Fparent.test"></iframe>'
        def route(request):
            url = urlparse(request.request.url)
            if url.hostname == "parent.test":
                request.fulfill(body=host, content_type="text/html")
            elif url.path.endswith("capture.js"):
                request.fulfill(body=capture_js, content_type="text/javascript")
            elif url.path.endswith("capture.html"):
                request.fulfill(body=capture_html, content_type="text/html")
            else:
                query = parse_qs(url.query)
                board = query.get("id", ["home"])[0]
                source_context = query.get("source", ["pause" if board == "help" else "home"])[0]
                if board == "settings":
                    markup = '<section class="settings-modal"><button class="close" data-target="home">Close</button><button class="toggle on" role="switch" aria-checked="true">Sound</button><button data-target="help">Help</button><button class="primary" data-target="home">Done</button><button onclick="window.opaque=true">Opaque</button></section>'
                elif board == "help":
                    markup = '<section class="help-modal"><button data-target="settings">Return to settings</button></section>'
                else:
                    markup = '<button data-target="settings" data-source="' + board + '">Settings</button>'
                bootstrap = '<script>window.boards=' + json.dumps(boards) + ';window.resolveBoardId=id=>id;document.addEventListener("click",()=>{});</script>'
                request.fulfill(body='<!doctype html><main id="artboard" data-source-context="' + source_context + '">' + markup + '</main>' + bootstrap, content_type="text/html")
        context.route("**/*", route)
        host_page = context.new_page()
        try:
            host_page.goto("https://parent.test/")
            host_page.wait_for_function("window.captured||window.captureError")
            self.assertIsNone(host_page.evaluate("window.captureError"))
            pages = host_page.evaluate("window.captured")
        finally:
            context.close()
        settings = next(page for page in pages if page["id"] == "settings")
        self.assertEqual(settings["migration"]["interactions"]["switches"], 1)
        self.assertEqual(settings["migration"]["interactions"]["inlineHandlers"], 1)
        self.assertTrue(any("inline event" in warning for warning in settings["migration"]["warnings"]))
        self.assertTrue(any("not replayed" in warning for warning in settings["migration"]["warnings"]))
        self.assertEqual(len(pages), 9)
        self.assertEqual(len(settings["migration"]["contextVariants"]), 2)
        self.fixture.mount([], mode="preview", pages=pages)
        page = self.fixture.page
        page.evaluate("instance.navigate('game')")
        page.get_by_role("button", name="Settings", exact=True).click()
        page.wait_for_function("instance.debugStats.listeners===4")
        self.assertEqual(page.locator('[data-source-context="game"]').count(), 1)
        switch = page.get_by_role("switch")
        switch.click()
        self.assertEqual(switch.get_attribute("aria-checked"), "false")
        self.assertNotIn("on", switch.get_attribute("class").split())
        page.get_by_role("button", name="Close", exact=True).click()
        self.assertEqual(page.evaluate("events.filter(e=>e.type==='studio-navigate').at(-1).pageId"), "game")
        page.evaluate("instance.navigate('pause')")
        page.get_by_role("button", name="Settings", exact=True).click()
        self.assertEqual(page.locator('[data-source-context="pause"]').count(), 1)
        page.get_by_role("button", name="Done", exact=True).click()
        self.assertEqual(page.evaluate("events.filter(e=>e.type==='studio-navigate').at(-1).pageId"), "pause")
        page.evaluate("instance.navigate('home')")
        page.get_by_role("button", name="Settings", exact=True).click()
        page.get_by_role("button", name="Help", exact=True).click()
        page.get_by_role("button", name="Return to settings", exact=True).click()
        page.get_by_role("button", name="Done", exact=True).click()
        self.assertEqual(page.evaluate("events.filter(e=>e.type==='studio-navigate').at(-1).pageId"), "home")
        self.assertEqual(page.evaluate("events.filter(e=>e.type==='studio-error')"), [])


if __name__ == "__main__":
    unittest.main()
