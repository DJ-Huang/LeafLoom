"""Explicit browser contracts for the portable Studio runtime.

Run with ``python tests/studio_runtime_browser.py``. This intentionally stays out
of discovery: it needs Playwright and an installed Chromium browser.
"""
from __future__ import annotations

from pathlib import Path
import os
import unittest
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


RUNTIME = Path(__file__).resolve().parents[1] / "vault_rag/design_assets/studio"


class StudioRuntimeBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        bundled = Path(cls.playwright.chromium.executable_path)
        chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        executable = Path(os.environ["LEAFLOOM_BROWSER_EXECUTABLE"]) if os.environ.get("LEAFLOOM_BROWSER_EXECUTABLE") else bundled if bundled.exists() else chrome
        if not executable.exists():
            cls.playwright.stop()
            raise unittest.SkipTest("Install Chromium to run the Studio browser contracts")
        cls.browser = cls.playwright.chromium.launch(executable_path=str(executable), headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1000, "height": 800})
        self.page.set_content('<style>html,body,#studio-root{margin:0;width:100%;height:100%}</style><main id="studio-root"></main>')
        self.page.add_style_tag(path=str(RUNTIME / "runtime.css"))
        self.page.add_script_tag(path=str(RUNTIME / "runtime.js"))

    def tearDown(self):
        self.page.close()

    def mount(self, nodes, *, mode="edit", **extra):
        document = {"schemaVersion": 1, "id": "project", "name": "Test", "assets": {}, "scripts": {}, "components": {}, "pages": [{"id": "home", "width": 800, "height": 600, "nodes": nodes}]}
        document.update(extra)
        self.page.evaluate("""({document, mode}) => {
          window.events=[];
          if(window.instance) window.instance.dispose();
          window.instance=LeafLoomStudio.mount(window.document.getElementById('studio-root'), document, {mode, assetBase:'file:///studio-export/', onMessage: data => events.push(data)});
        }""", {"document": document, "mode": mode})

    def test_nested_rotated_drag_is_one_transaction_and_shortcuts_reach_host(self):
        self.mount([{"id": "parent", "type": "container", "style": {"x": 500, "y": 100, "width": 300, "height": 300, "rotate": 90}, "children": [{"id": "child", "type": "shape", "style": {"x": 20, "y": 30, "width": 50, "height": 50, "background": "red"}}]}])
        child = self.page.locator('[data-studio-select-id="child"]')
        rect = child.bounding_box()
        zoom = self.page.evaluate("document.querySelector('.studio-stage').getBoundingClientRect().width/800")
        self.page.mouse.move(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
        self.page.mouse.down()
        self.page.mouse.move(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2 + 40 * zoom, steps=5)
        self.page.mouse.up()
        commits = self.page.evaluate("events.filter(e=>e.type==='studio-commit')")
        self.assertEqual(len(commits), 1)
        self.assertEqual(len(commits[0]["commands"]), 1)
        patch = commits[0]["commands"][0]["patch"]["style"]
        self.assertAlmostEqual(patch["x"], 60, delta=.1)
        self.assertAlmostEqual(patch["y"], 30, delta=.1)
        self.page.keyboard.press("Control+z")
        self.assertEqual(self.page.evaluate("events.at(-1).action"), "undo")

    def test_preview_modules_parameters_dependency_and_cleanup(self):
        script = "import {answer} from './dependency.js'; export function mount(ctx){console.log('mounted');ctx.el.dataset.answer=String(answer+ctx.props.offset);ctx.setInterval(()=>ctx.el.dataset.ticks=String(Number(ctx.el.dataset.ticks||0)+1),10);return ()=>{globalThis.stopped=(globalThis.stopped||0)+1;}}"
        self.mount([{"id": "scripted", "type": "shape", "style": {"width": 100, "height": 100}, "script": {"moduleId": "module", "props": {"offset": 2}}, "animation": {"preset": "breathe", "iterations": "Infinity"}}], mode="preview", scripts={"module": {"path": "Design/Scripts/module.js", "source": script}, "dependency": {"path": "Design/Scripts/dependency.js", "source": "export const answer=40;"}})
        self.page.wait_for_function("document.querySelector('[data-studio-node=scripted] .studio-content').dataset.answer==='42'")
        self.assertEqual(self.page.evaluate("events.filter(e=>e.type==='studio-error')"), [])
        self.assertEqual(self.page.evaluate("events.find(e=>e.type==='studio-console').args"), ["mounted"])
        self.assertGreater(self.page.evaluate("document.querySelector('[data-studio-node=scripted] .studio-content').getAnimations().length"), 0)
        self.page.evaluate("instance.setMode('edit')")
        self.assertEqual(self.page.evaluate("window.stopped"), 1)
        self.assertEqual(self.page.evaluate("document.querySelector('[data-studio-node=scripted] .studio-content').getAnimations().length"), 0)

    def test_authored_markup_scopes_css_ids_and_preserves_layout(self):
        authored = [{"id": "root", "type": "element", "props": {"authored": True, "tag": "section", "attributes": {"class": "original"}}, "children": [{"id": "leaf", "type": "element", "props": {"authored": True, "tag": "span", "attributes": {"id": "label"}, "text": "Hello"}}]}]
        pages = [{"id": "home", "width": 800, "height": 600, "nodes": [{"id": "embed1", "type": "page", "props": {"pageId": "other"}, "style": {"width": 200, "height": 100}}, {"id": "embed2", "type": "page", "props": {"pageId": "other"}, "style": {"x": 250, "width": 200, "height": 100}}]}, {"id": "other", "width": 200, "height": 100, "css": ".original {display:flex;padding:17px} .original #label {color:rgb(1, 2, 3)}", "nodes": authored}]
        self.mount([], pages=pages)
        leaves = self.page.locator("span.studio-authored")
        self.assertEqual(leaves.count(), 2)
        self.assertNotEqual(leaves.nth(0).get_attribute("id"), leaves.nth(1).get_attribute("id"))
        self.assertEqual(leaves.nth(0).evaluate("el=>getComputedStyle(el).color"), "rgb(1, 2, 3)")
        self.assertEqual(leaves.nth(0).evaluate("el=>getComputedStyle(el).position"), "static")
        self.assertEqual(self.page.locator("section.original").nth(0).evaluate("el=>getComputedStyle(el).padding"), "17px")

    def test_incremental_geometry_update_preserves_dom_and_undoes_authored_offsets(self):
        self.mount([{"id": "native", "type": "element", "props": {"tag": "p", "authored": True, "text": "Original", "attributes": {"style": "color:blue"}}, "style": {"x": 10, "y": 20, "color": "red"}}])
        self.page.evaluate("""() => {
          const el=document.querySelector('[data-studio-node=native]');el.dataset.identity='preserved';
          const doc=instance.document;doc.pages[0].nodes[0].style={};doc.pages[0].nodes[0].props.text='Updated';
          window.reused=instance.update(doc,{mode:'edit'});
        }""")
        node = self.page.locator('[data-studio-node="native"]')
        self.assertTrue(self.page.evaluate("window.reused"))
        self.assertEqual(node.get_attribute("data-identity"), "preserved")
        self.assertEqual(node.inner_text(), "Updated")
        self.assertEqual(node.evaluate("el=>getComputedStyle(el).translate"), "none")
        self.assertEqual(node.evaluate("el=>getComputedStyle(el).color"), "rgb(0, 0, 255)")

    def test_cycles_fail_visibly_and_custom_html_is_sandboxed(self):
        self.mount([{"id": "self", "type": "page", "props": {"pageId": "home"}}, {"id": "custom", "type": "html", "props": {"html": "<html><body><script>console.log('custom log');throw new Error('custom failure')</script></body></html>"}}])
        self.assertEqual(self.page.locator(".studio-missing").inner_text(), "Cyclic page embedding")
        frame = self.page.locator("iframe")
        self.assertEqual(frame.get_attribute("sandbox"), "")
        self.assertIsNone(self.page.evaluate("window.hacked"))
        self.page.evaluate("instance.setMode('preview')")
        self.page.wait_for_function("events.some(e=>e.type==='studio-error'&&e.nodeId==='custom'&&e.message.includes('custom failure'))")
        self.assertEqual(self.page.evaluate("events.find(e=>e.type==='studio-console'&&e.nodeId==='custom').args"), ["custom log"])

    def test_authored_parent_text_updates_immediately_without_losing_children(self):
        self.mount([{"id": "parent", "type": "element", "props": {"authored": True, "tag": "p", "text": "Before "},
                     "children": [{"id": "child", "type": "element", "props": {"authored": True, "tag": "strong", "text": "Child"}}]}])
        for text in ("After ", "", "Restored "):
            reused = self.page.evaluate("""text => {
              const doc=instance.document;doc.pages[0].nodes[0].props.text=text;
              return instance.update(doc,{mode:'edit',selectedIds:['parent']});
            }""", text)
            self.assertFalse(reused)
            parent = self.page.locator('[data-studio-node="parent"]')
            self.assertEqual(parent.text_content(), text + "Child")
            self.assertEqual(parent.locator('[data-studio-node="child"]').text_content(), "Child")
            self.assertEqual(parent.locator('strong').count(), 1)
        self.assertEqual(self.page.evaluate("events.filter(e=>e.type==='studio-error')"), [])

    def test_inline_text_commits_once_and_escape_cancels(self):
        self.mount([{"id": "label", "type": "text", "style": {"x": 80, "y": 60, "width": 200, "height": 60}, "props": {"text": "Before"}}])
        text = self.page.locator('[data-studio-node="label"] > .studio-content')
        text.dblclick()
        self.assertEqual(text.get_attribute("contenteditable"), "plaintext-only")
        self.page.keyboard.insert_text("After")
        self.assertEqual(text.inner_text(), "After")
        self.page.keyboard.press("Control+z")
        self.assertFalse(self.page.evaluate("events.some(e=>e.type==='studio-shortcut')"))
        self.page.keyboard.press("Control+Shift+z")
        self.page.keyboard.press("Enter")
        self.assertEqual(text.inner_text(), "After")
        self.assertEqual(self.page.evaluate("events.filter(e=>e.type==='studio-commit').length"), 1)
        self.assertEqual(self.page.evaluate("events.find(e=>e.type==='studio-commit').commands[0].patch.props.text"), "After")
        text.dblclick()
        self.page.keyboard.insert_text("Cancelled")
        self.page.keyboard.press("Escape")
        self.assertEqual(text.inner_text(), "After")
        self.assertEqual(self.page.evaluate("events.filter(e=>e.type==='studio-commit').length"), 1)

    def test_bridge_pins_parent_origin_and_session(self):
        context = self.browser.new_context()
        runtime_js = (RUNTIME / "runtime.js").read_text()
        runtime_css = (RUNTIME / "runtime.css").read_text()
        runtime_html = (RUNTIME / "runtime.html").read_text()
        host = '<script>window.events=[];addEventListener("message", e=>events.push(e.data));</script><iframe id="canvas" src="http://studio.test/runtime.html?session=secret&parentOrigin=http%3A%2F%2Fparent.test"></iframe>'
        def route(request):
            url = request.request.url
            if urlparse(url).hostname == "parent.test":
                request.fulfill(body=host, content_type="text/html")
            elif "runtime.js" in url:
                request.fulfill(body=runtime_js, content_type="text/javascript")
            elif "runtime.css" in url:
                request.fulfill(body=runtime_css, content_type="text/css")
            else:
                request.fulfill(body=runtime_html, content_type="text/html")
        context.route("**/*", route)
        host_page = context.new_page()
        try:
            host_page.goto("http://parent.test/")
            host_page.wait_for_function("events.some(e=>e.type==='studio-ready'&&e.session==='secret')")
            document = {"schemaVersion": 1, "id": "safe", "pages": [{"id": "home", "nodes": []}]}
            host_page.evaluate("doc=>canvas.contentWindow.postMessage({type:'studio-init',session:'wrong',document:doc},'*')", document)
            self.assertEqual(host_page.frame_locator("iframe").locator(".studio-stage").count(), 0)
            host_page.evaluate("doc=>canvas.contentWindow.postMessage({type:'studio-init',session:'secret',document:doc},'http://studio.test')", document)
            host_page.wait_for_function("events.some(e=>e.type==='studio-rendered')")
            self.assertEqual(host_page.frame_locator("iframe").locator(".studio-stage").count(), 1)
        finally:
            context.close()

    def test_camera_zoom_pan_and_structural_updates_preserve_view(self):
        self.mount([{"id": "box", "type": "shape", "style": {"x": 200, "y": 200, "width": 100, "height": 80}}])
        self.page.evaluate("instance.setZoom(2);instance.setTool('hand')")
        self.assertEqual(self.page.evaluate("instance.camera.zoom"), 2)
        self.page.mouse.move(500, 400)
        self.page.mouse.down()
        self.page.mouse.move(560, 440, steps=4)
        self.page.mouse.up()
        before = self.page.evaluate("instance.camera")
        self.assertEqual(before["x"], 370)
        self.assertEqual(before["y"], 280)
        self.assertEqual(self.page.evaluate("events.filter(e=>e.type==='studio-commit').length"), 0)
        self.page.evaluate("""() => {const doc=instance.document;doc.pages[0].nodes.push({id:'new',type:'shape',style:{width:20,height:20}});instance.update(doc,{pageId:'home',mode:'edit'});} """)
        self.assertEqual(self.page.evaluate("instance.camera"), before)
        self.page.set_viewport_size({"width": 1100, "height": 850})
        self.page.wait_for_timeout(50)
        self.assertEqual(self.page.evaluate("instance.camera"), before)
        self.page.evaluate("instance.setMode('preview');instance.setMode('edit')")
        self.assertEqual(self.page.evaluate("instance.camera"), before)
        self.page.evaluate("instance.setZoom(NaN);instance.setZoom('2')")
        self.assertEqual(self.page.evaluate("instance.camera.zoom"), 2)
        self.page.evaluate("instance.setZoom(100)")
        self.assertEqual(self.page.evaluate("instance.camera.zoom"), 8)

    def test_camera_fits_new_pages_and_retains_each_page_view(self):
        pages = [{"id": "home", "width": 800, "height": 600, "nodes": []}, {"id": "other", "width": 2000, "height": 1000, "nodes": []}]
        self.mount([], pages=pages)
        initial = self.page.evaluate("instance.camera.zoom")
        self.page.evaluate("instance.setZoom(.75);instance.navigate('other')")
        self.assertLess(self.page.evaluate("instance.camera.zoom"), initial)
        self.page.evaluate("instance.setZoom(.5);instance.navigate('home')")
        self.assertEqual(self.page.evaluate("instance.camera.zoom"), .75)
        self.page.evaluate("instance.navigate('other')")
        self.assertEqual(self.page.evaluate("instance.camera.zoom"), .5)
        self.page.evaluate("instance.fit();const doc=instance.document;doc.pages[1].width=4000;instance.update(doc,{pageId:'other'});")
        self.assertAlmostEqual(self.page.evaluate("instance.camera.zoom"), .23)
        self.page.evaluate("instance.setZoom(3);const doc=instance.document;doc.id='different-project';instance.update(doc,{pageId:'home'});")
        self.assertAlmostEqual(self.page.evaluate("instance.camera.zoom"), initial)
        self.page.evaluate("instance.setZoom(3);const doc=instance.document;doc.id='same-page-new-project';instance.update(doc,{pageId:'home'});")
        self.assertAlmostEqual(self.page.evaluate("instance.camera.zoom"), initial)

    def test_space_hand_zoom_anchor_fit_selection_and_shortcuts(self):
        self.mount([{"id": "box", "type": "shape", "style": {"x": 200, "y": 200, "width": 100, "height": 80}}])
        self.page.evaluate("instance.setZoom(1);document.querySelector('.studio-viewport').focus()")
        self.page.keyboard.down("Space")
        self.page.mouse.move(500, 400)
        self.page.mouse.down()
        self.page.mouse.move(530, 420, steps=3)
        self.page.mouse.up()
        self.page.keyboard.up("Space")
        self.assertEqual(self.page.evaluate("instance.camera.x"), 370)
        self.assertEqual(self.page.evaluate("instance.camera.tool"), "select")
        self.assertEqual(self.page.locator(".studio-hand").count(), 0)
        self.assertEqual(self.page.evaluate("events.filter(e=>e.type==='studio-commit').length"), 0)
        self.page.evaluate("instance.select(['box']);instance.fitSelection()")
        box = self.page.locator('[data-studio-select-id="box"]').bounding_box()
        self.assertAlmostEqual(box["x"] + box["width"] / 2, 500, delta=1)
        self.assertAlmostEqual(box["y"] + box["height"] / 2, 400, delta=1)
        self.page.keyboard.press("Control+0")
        self.assertEqual(self.page.evaluate("instance.camera.zoom"), 1)
        self.page.keyboard.press("h")
        self.assertEqual(self.page.evaluate("instance.camera.tool"), "hand")
        self.page.keyboard.press("v")
        self.assertEqual(self.page.evaluate("instance.camera.tool"), "select")
        self.page.evaluate("instance.fit();instance.setZoom(1)")
        self.page.mouse.move(600, 400)
        self.page.keyboard.down("Control")
        self.page.mouse.wheel(0, -20)
        self.page.keyboard.up("Control")
        self.page.wait_for_timeout(80)
        view = self.page.evaluate("instance.camera")
        self.assertGreater(view["zoom"], 1)
        self.assertAlmostEqual(view["x"] + 100 / view["zoom"], 500, delta=.1)

    def test_native_presets_compose_with_authored_geometry(self):
        nodes = [{"id": preset, "type": "element", "props": {"authored": True, "tag": "div", "text": preset},
                  "style": {"x": 120, "y": 90, "width": 100, "height": 70, "scaleX": 1.5, "scaleY": 2, "rotate": 30, "opacity": .6},
                  "animation": {"preset": preset, "duration": 1000, "easing": "linear"}} for preset in ("breathe", "bounce", "spin", "fade")]
        self.mount(nodes, mode="preview")
        values = self.page.evaluate("""() => Object.fromEntries(['breathe','bounce','spin','fade'].map(id=>{
          const el=document.querySelector('[data-studio-node="'+id+'"]'),animation=el.getAnimations()[0];
          animation.pause();animation.currentTime=500;
          const style=getComputedStyle(el);return [id,{translate:style.translate,scale:style.scale,rotate:style.rotate,opacity:style.opacity}];
        }))""")
        self.assertEqual(values["breathe"]["translate"], "120px 90px")
        self.assertEqual(values["breathe"]["scale"], "1.5675 2.09")
        self.assertEqual(values["bounce"]["translate"], "120px 74px")
        self.assertEqual(values["spin"]["rotate"], "210deg")
        self.assertAlmostEqual(float(values["fade"]["opacity"]), .3, places=4)
        self.page.evaluate("instance.setMode('edit')")
        node = self.page.locator('[data-studio-node="breathe"]')
        self.assertEqual(node.evaluate("el=>getComputedStyle(el).translate"), "120px 90px")
        self.assertEqual(node.evaluate("el=>getComputedStyle(el).scale"), "1.5 2")
        self.assertEqual(node.evaluate("el=>getComputedStyle(el).rotate"), "30deg")

    def test_presets_respect_initial_and_live_reduced_motion(self):
        nodes = [{"id": trigger, "type": "button", "props": {"text": trigger},
                  "style": {"x": index * 150, "y": 80, "width": 120, "height": 60},
                  "animation": {"preset": "fade" if trigger == "load" else "breathe", "trigger": trigger,
                                "duration": 10000, "iterations": "Infinity"}}
                 for index, trigger in enumerate(("load", "click", "hover"))]
        self.page.emulate_media(reduced_motion="reduce")
        self.mount(nodes, mode="preview")
        self.page.evaluate("""() => {
          document.querySelector('[data-studio-node=click] button').click();
          document.querySelector('[data-studio-node=hover] button').focus();
        }""")
        self.assertEqual(self.page.evaluate("instance.debugStats.animations"), 0)
        self.assertEqual(self.page.evaluate("document.querySelector('.studio-stage').getAnimations({subtree:true}).length"), 0)
        self.assertEqual(self.page.locator('[data-studio-node=load] button').evaluate("el=>getComputedStyle(el).opacity"), "1")

        self.page.emulate_media(reduced_motion="no-preference")
        self.page.wait_for_function("instance.debugStats.animations===1")
        self.assertEqual(self.page.locator('[data-studio-node=click] button').evaluate("el=>el.getAnimations().length"), 0)
        self.assertEqual(self.page.locator('[data-studio-node=hover] button').evaluate("el=>el.getAnimations().length"), 0)
        self.page.evaluate("""() => {
          document.querySelector('[data-studio-node=click] button').click();
          document.querySelector('[data-studio-node=hover] button').dispatchEvent(new MouseEvent('mouseenter'));
        }""")
        self.assertEqual(self.page.evaluate("instance.debugStats.animations"), 3)
        self.page.emulate_media(reduced_motion="reduce")
        self.page.wait_for_function("instance.debugStats.animations===0")
        self.assertEqual(self.page.evaluate("document.querySelector('.studio-stage').getAnimations({subtree:true}).length"), 0)
        self.assertEqual(self.page.locator('[data-studio-node=load] button').evaluate("el=>getComputedStyle(el).opacity"), "1")
        self.page.evaluate("instance.dispose()")
        self.page.emulate_media(reduced_motion="no-preference")
        self.assertEqual(self.page.evaluate("instance.debugStats.listeners"), 0)
        self.assertEqual(self.page.evaluate("instance.debugStats.animations"), 0)
        self.assertEqual(self.page.evaluate("events.filter(e=>e.type==='studio-error')"), [])

    def test_hover_presets_support_keyboard_and_touch_without_replacing_tab_order(self):
        self.mount([{"id": "hover", "type": "shape", "style": {"x": 80, "y": 80, "width": 120, "height": 60},
                     "animation": {"preset": "breathe", "trigger": "hover", "duration": 10000}},
                    {"id": "authored", "type": "element", "props": {"authored": True, "tag": "div", "attributes": {"tabindex": "-1"}},
                     "animation": {"preset": "breathe", "trigger": "hover"}}], mode="preview")
        hover = self.page.locator('[data-studio-node=hover] .studio-content')
        self.assertEqual(hover.get_attribute("tabindex"), "0")
        self.assertEqual(self.page.locator('[data-studio-node=authored]').get_attribute("tabindex"), "-1")
        self.page.locator('.studio-viewport').focus()
        self.page.keyboard.press("Tab")
        self.assertTrue(hover.evaluate("el=>el===document.activeElement"))
        self.assertEqual(hover.evaluate("el=>el.getAnimations().length"), 1)
        hover.evaluate("el=>{window.previousPreset=el.getAnimations()[0];el.blur();}")
        hover.dispatch_event("pointerdown", {"pointerType": "touch", "pointerId": 1, "isPrimary": True})
        self.assertEqual(self.page.evaluate("previousPreset.playState"), "idle")
        self.assertEqual(hover.evaluate("el=>el.getAnimations().length"), 1)
        self.assertEqual(self.page.evaluate("instance.debugStats.animations"), 1)
        self.page.evaluate("instance.setMode('edit')")
        self.assertIsNone(self.page.locator('[data-studio-node=hover] .studio-content').get_attribute("tabindex"))
        self.assertEqual(self.page.evaluate("instance.debugStats.animations"), 0)

    def test_replaying_presets_replaces_effects_and_keeps_resources_bounded(self):
        self.mount([{"id": trigger, "type": "button", "props": {"text": trigger},
                     "style": {"x": index * 150, "y": 80, "width": 120, "height": 60},
                     "animation": {"preset": "breathe", "trigger": trigger, "duration": 10000}}
                    for index, trigger in enumerate(("click", "hover"))], mode="preview")
        result = self.page.evaluate("""() => {
          const click=document.querySelector('[data-studio-node=click] button');
          const hover=document.querySelector('[data-studio-node=hover] button');
          const listeners=instance.debugStats.listeners;
          click.click();hover.dispatchEvent(new MouseEvent('mouseenter'));
          const first=[click.getAnimations()[0],hover.getAnimations()[0]];
          first.forEach(animation=>animation.finish());
          let peak=0;
          for(let index=0;index<200;index++) {
            click.click();hover.dispatchEvent(new MouseEvent('mouseenter'));
            peak=Math.max(peak,instance.debugStats.animations);
          }
          return {peak,firstStates:first.map(animation=>animation.playState),
            effects:[click.getAnimations().length,hover.getAnimations().length],
            listenersBefore:listeners,listenersAfter:instance.debugStats.listeners};
        }""")
        self.assertEqual(result["peak"], 2)
        self.assertEqual(result["firstStates"], ["idle", "idle"])
        self.assertEqual(result["effects"], [1, 1])
        self.assertEqual(result["listenersBefore"], result["listenersAfter"])
        for _ in range(3):
            self.page.evaluate("instance.setMode('edit')")
            stats = self.page.evaluate("instance.debugStats")
            for key in ("listeners", "timers", "frames", "animations", "objectUrls", "previewGroups"):
                self.assertEqual(stats[key], 0, key)
            self.page.evaluate("instance.setMode('preview');document.querySelector('[data-studio-node=click] button').click()")
            self.assertEqual(self.page.evaluate("instance.debugStats.animations"), 1)
        self.page.evaluate("instance.dispose()")
        self.assertEqual(self.page.evaluate("instance.debugStats.animations"), 0)
        self.assertEqual(self.page.evaluate("instance.debugStats.listeners"), 0)

    def test_stopped_script_resources_release_bookkeeping_and_dispose_in_reverse_order(self):
        source = """export function mount(ctx) {
          globalThis.scriptContext=ctx;globalThis.cleanupOrder=[];globalThis.lateCallbacks=0;
          const target=new EventTarget(),remove=target.removeEventListener.bind(target);
          target.removeEventListener=(type,...args)=>{cleanupOrder.push(type);remove(type,...args);};
          ctx.on(target,'first',()=>{});ctx.on(target,'second',()=>{});
          ctx.el.dataset.ready='true';
          return()=>{cleanupOrder.push('script');delete globalThis.scriptContext;};
        }"""
        self.mount([{"id": "scripted", "type": "shape", "style": {"width": 120, "height": 60},
                     "script": {"source": source}}], mode="preview")
        self.page.wait_for_function("document.querySelector('[data-studio-node=scripted] .studio-content').dataset.ready==='true'")
        result = self.page.evaluate("""async () => {
          const ctx=scriptContext,before=instance.debugStats;
          for(let index=0;index<500;index++) {
            const stopFrame=ctx.onFrame(()=>{lateCallbacks++;});
            const stopListener=ctx.onEvent('transient',()=>{});
            stopFrame();stopFrame();stopListener();stopListener();
          }
          const afterStops=instance.debugStats,settled=[];
          for(let batch=0;batch<8;batch++) {
            await Promise.all(Array.from({length:50},()=>new Promise(resolve=>ctx.setTimeout(resolve,0))));
            settled.push(instance.debugStats.ownedResources);
          }
          return {before,afterStops,afterTimers:instance.debugStats,settled,lateCallbacks};
        }""")
        self.assertEqual(result["afterStops"]["ownedResources"], result["before"]["ownedResources"])
        self.assertEqual(result["afterStops"]["listeners"], result["before"]["listeners"])
        self.assertEqual(result["afterStops"]["frames"], 0)
        self.assertEqual(result["settled"], [result["before"]["ownedResources"]] * 8)
        self.assertEqual(result["afterTimers"]["timers"], 0)
        self.assertEqual(result["lateCallbacks"], 0)
        self.page.evaluate("""() => {
          scriptContext.onFrame(()=>{lateCallbacks++;});
          scriptContext.setTimeout(()=>{lateCallbacks++;},0);
          scriptContext.setInterval(()=>{lateCallbacks++;},1);
          instance.dispose();
        }""")
        self.page.wait_for_timeout(50)
        self.assertEqual(self.page.evaluate("cleanupOrder"), ["script", "second", "first"])
        self.assertEqual(self.page.evaluate("lateCallbacks"), 0)
        stats = self.page.evaluate("instance.debugStats")
        for key in ("listeners", "timers", "frames", "animations", "ownedResources", "objectUrls", "previewGroups"):
            self.assertEqual(stats[key], 0, key)
        self.assertEqual(self.page.evaluate("events.filter(e=>e.type==='studio-error')"), [])

    def test_embedded_pages_namespace_css_keyframes_and_inline_names(self):
        def target(page_id, end, inline=False):
            return {"id": page_id, "width": 100, "height": 100,
                    "css": '@keyframes pulse {from {opacity:0} to {opacity:' + str(end) + '}} .motion {animation:pulse 1s linear both}',
                    "nodes": [{"id": "motion", "type": "element", "props": {"tag": "div", "authored": True, "text": page_id,
                              "attributes": {"class": "motion", **({"style": "animation: pulse 1s linear both"} if inline else {})}}}]}
        pages = [{"id": "home", "width": 800, "height": 600, "nodes": [
            {"id": "one", "type": "page", "props": {"pageId": "first"}, "style": {"width": 100, "height": 100}},
            {"id": "two", "type": "page", "props": {"pageId": "second"}, "style": {"x": 150, "width": 100, "height": 100}}]},
            target("first", .4), target("second", 1, True)]
        self.mount([], mode="preview", pages=pages)
        values = self.page.locator(".motion").evaluate_all("""elements=>elements.map(el=>{
          const animation=el.getAnimations()[0];animation.pause();animation.currentTime=500;
          return {name:getComputedStyle(el).animationName,opacity:Number(getComputedStyle(el).opacity)};
        })""")
        self.assertNotEqual(values[0]["name"], values[1]["name"])
        self.assertAlmostEqual(values[0]["opacity"], .2, places=4)
        self.assertAlmostEqual(values[1]["opacity"], .5, places=4)


if __name__ == "__main__":
    # Keep the existing CI entry point while extending its renderer contracts.
    import subprocess
    import sys
    result = unittest.main(exit=False).result
    canvas = subprocess.run([sys.executable, str(Path(__file__).with_name("studio_canvas_polish_browser.py"))], check=False)
    raise SystemExit(0 if result.wasSuccessful() and canvas.returncode == 0 else 1)
