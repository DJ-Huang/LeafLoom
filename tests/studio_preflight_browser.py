"""Browser contracts for text preflight, bounded suggestions, and static mode.
Run LEAFLOOM_BROWSER_EXECUTABLE=/usr/bin/chromium python tests/studio_preflight_browser.py.
"""
import unittest
from studio_runtime_browser import StudioRuntimeBrowserTests


class StudioPreflightBrowserTests(StudioRuntimeBrowserTests):
    # Reuse fixtures without re-running the base suite here.
    def test_preflight_reports_overflow_and_honest_unicode_risk(self):
        self.mount([
            {"id": "long", "type": "text", "props": {"text": "LONG TEXT " * 30}, "style": {"width": 80, "height": 20, "fontSize": 24}},
            {"id": "multi", "type": "text", "props": {"text": "中文 日本語 🦊"}, "style": {"y": 100, "width": 400, "height": 80}},
            {"id": "hidden", "hidden": True, "type": "text", "props": {"text": "Too long"}, "style": {"width": 1, "height": 1}},
            {"id": "html", "type": "html", "props": {"html": "<p>Text</p>"}, "style": {"width": 100, "height": 100}},
        ])
        result = self.page.evaluate("instance.preflight()")
        self.assertTrue(any(x["kind"] == "text-overflow" and x["nodeId"] == "long" for x in result["issues"]))
        self.assertTrue(any(x["kind"] == "missing-glyph-risk" and x["nodeId"] == "multi" for x in result["issues"]))
        self.assertTrue(any(x["kind"] == "uninspected-html" for x in result["issues"]))
        self.assertFalse(any(x["nodeId"] == "hidden" for x in result["issues"]))
        self.assertTrue(result["limitations"])
        self.assertTrue(all(x["pageId"] == "home" and "measurements" in x for x in result["issues"]))

    def test_fit_suggests_readable_patch_without_mutating(self):
        self.mount([{"id": "fit", "type": "text", "props": {"text": "MMMMMMMMMM"}, "style": {"width": 180, "height": 40, "fontSize": 24, "fontFamily": "monospace", "whiteSpace": "nowrap"}}])
        # Narrow to a width just below the measured text width for a bounded fit.
        self.page.evaluate("""() => {const el=document.querySelector('.studio-content'); el.parentElement.style.width='135px';}""")
        before = self.page.evaluate("JSON.stringify(instance.document)")
        result = self.page.evaluate("instance.fitText('fit',{minFontSize:12,maxReduction:.2})")
        self.assertIsNotNone(result["patch"])
        size = result["patch"]["style"]["fontSize"]
        self.assertGreaterEqual(size, 19.2)
        self.assertLess(size, 24)
        self.assertFalse(result["measurements"]["after"]["overflowX"])
        self.assertEqual(self.page.evaluate("JSON.stringify(instance.document)"), before)
        self.assertEqual(self.page.locator('.studio-content').evaluate("el=>getComputedStyle(el).fontSize"), "24px")
        self.assertEqual(self.page.evaluate("events.filter(e=>e.type==='studio-commit')"), [])
        self.assertIsNone(self.page.evaluate("instance.fitText('fit',{minFontSize:8})")["patch"])
        self.page.evaluate("document.querySelector('.studio-node').style.width='5px'")
        self.assertIsNone(self.page.evaluate("instance.fitText('fit',{minFontSize:12})")["patch"])

    def test_font_load_failure_is_risk(self):
        self.mount([{"id": "font", "type": "text", "props": {"text": "Hello"}, "style": {"width": 100, "height": 50}}])
        self.page.evaluate("document.fonts.check = () => false")
        self.assertTrue(any(x["kind"] == "font-load" for x in self.page.evaluate("instance.preflight()")["issues"]))

    def test_variant_projection_and_readonly_do_not_rewrite_source(self):
        self.mount([{"id": "title", "type": "text", "props": {"text": "Authored", "bindingKey": "headline"}, "style": {"width": 300, "height": 100, "fontSize": 32}}],
                   bindings={"headline": {"key": "headline", "kind": "text", "value": "Source", "revision": 2}},
                   variants={"ja": {"id": "ja", "values": {"headline": {"value": "翻訳", "sourceRevision": 1}}, "layout": {"title": {"fontSize": 20}}, "pageLayout": {"home": {"width": 500}}}})
        self.assertEqual(self.page.locator('.studio-content').text_content(), 'Source')
        self.page.evaluate("instance.update(instance.document,{variantId:'ja',readOnly:true,selectedIds:['title']})")
        self.assertEqual(self.page.locator('.studio-content').text_content(), '翻訳')
        self.assertEqual(self.page.locator('.studio-content').evaluate('el=>getComputedStyle(el).fontSize'), '20px')
        self.assertEqual(self.page.evaluate("instance.document.pages[0].nodes[0].props.text"), 'Authored')
        self.assertEqual(self.page.evaluate("instance.document.pages[0].width"), 800)
        self.page.evaluate("instance.action('nudge-right')")
        self.page.locator('.studio-content').dblclick()
        self.assertEqual(self.page.locator('[contenteditable]').count(), 0)
        self.assertEqual(self.page.evaluate("events.filter(e=>e.type==='studio-commit')"), [])
        self.page.evaluate("instance.update(instance.document,{variantId:null,readOnly:false})")
        self.assertEqual(self.page.locator('.studio-content').text_content(), 'Source')
        self.assertEqual(self.page.locator('.studio-content').evaluate('el=>getComputedStyle(el).fontSize'), '32px')

    def test_already_resolved_export_does_not_reapply_source_bindings(self):
        self.mount([{"id": "title", "type": "text", "props": {"text": "Rendered translation", "bindingKey": "headline"}, "style": {"width": 300, "height": 100}}],
                   bindings={"headline": {"key": "headline", "kind": "text", "value": "Source", "revision": 1}})
        self.page.evaluate("""() => {const source=instance.document;instance.dispose();window.instance=LeafLoomStudio.mount(document.getElementById('studio-root'),source,{mode:'static',alreadyResolved:true});}""")
        self.assertEqual(self.page.locator('.studio-content').text_content(), 'Rendered translation')

    def test_static_ready_decodes_css_and_pseudo_images_and_freezes_smil(self):
        pixel = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=='
        self.mount([{"id": "background", "type": "shape", "style": {"width": 100, "height": 100, "backgroundImage": 'url("' + pixel + '")'}}], mode='static')
        self.page.evaluate("""pixel => {
          const style=document.createElement('style');style.textContent='.studio-stage::before{content:"";position:absolute;width:10px;height:10px;background-image:url("'+pixel+'#pseudo")}' ;document.head.appendChild(style);
          document.querySelector('.studio-stage').insertAdjacentHTML('beforeend','<svg width="20" height="20"><rect width="10" height="10"><animate attributeName="x" from="0" to="20" dur="1s" repeatCount="indefinite"/></rect></svg>');
        }""", pixel)
        result = self.page.evaluate('instance.readyForStatic()')
        self.assertGreaterEqual(result['resources'], 2)
        self.assertEqual(self.page.locator('svg').evaluate('el=>el.animationsPaused()'), True)
        self.assertAlmostEqual(self.page.locator('svg').evaluate('el=>el.getCurrentTime()'), 0, delta=.01)
        self.page.evaluate("document.querySelector('.studio-content').style.backgroundImage='url(data:image/png;base64,broken)' ")
        error = self.page.evaluate("instance.readyForStatic({timeoutMs:500}).then(()=>null,error=>error.message)")
        self.assertTrue(error)

    def test_static_ready_is_bounded_and_preview_unchanged(self):
        self.mount([{"id": "image", "type": "image", "props": {"src": "data:image/png;base64,broken"}, "style": {"width": 20, "height": 20}}], mode='static')
        self.page.evaluate("""() => {for(let i=0;i<3;i++){const img=document.createElement('img');img.src='data:image/png;base64,broken';document.querySelector('.studio-stage').appendChild(img);}}""")
        error = self.page.evaluate("instance.readyForStatic({maxResources:1}).then(()=>null,error=>error.message)")
        self.assertIn('limit', error)
        self.page.evaluate("instance.setMode('preview')")
        error = self.page.evaluate("instance.readyForStatic().then(()=>null,error=>error.message)")
        self.assertIn('only in static', error)

    def test_static_mode_is_page_sized_motion_free_script_free(self):
        self.mount([
            {"id": "motion", "type": "text", "props": {"text": "Still"}, "style": {"width": 100, "height": 50, "animation": "spin 1s infinite"}, "animation": {"preset": "breathe", "loop": True}, "script": {"source": "export function mount(){globalThis.ranStatic=true}"}},
            {"id": "html", "type": "html", "style": {"y": 100, "width": 100, "height": 100}, "props": {"html": '<script>document.body.dataset.ran="yes"</script><p>Hello</p>'}},
        ], mode="static")
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.locator('.studio-stage').bounding_box(), {"x": 0, "y": 0, "width": 800, "height": 600})
        self.assertEqual(self.page.locator('.studio-viewport').bounding_box(), {"x": 0, "y": 0, "width": 800, "height": 600})
        self.assertFalse(self.page.evaluate("!!window.ranStatic"))
        self.assertEqual(self.page.evaluate("document.getAnimations().length"), 0)
        self.assertEqual(self.page.locator('iframe').get_attribute('sandbox'), '')
        self.assertIn('script-src &apos;none&apos;', self.page.locator('iframe').get_attribute('srcdoc'))
        self.page.evaluate("instance.setZoom(3)")
        self.assertEqual(self.page.evaluate("instance.camera.zoom"), 1)
        self.page.evaluate("instance.setMode('preview')")
        self.assertIn('allow-scripts', self.page.locator('iframe').get_attribute('sandbox'))
        self.assertNotIn('script-src &apos;none&apos;', self.page.locator('iframe').get_attribute('srcdoc'))


if __name__ == '__main__':
    names = [name for name in StudioPreflightBrowserTests.__dict__ if name.startswith('test_')]
    suite = unittest.TestSuite(StudioPreflightBrowserTests(name) for name in names)
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
