"""Isolated renderer contracts for the Studio canvas and visual auto layout.

Run: python tests/studio_canvas_polish_browser.py
Uses the existing Chromium harness. No project files, network services, relaxed
browser security flags, or management-origin DOM access are required.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest
from urllib.parse import urlparse

import studio_runtime_browser as runtime_tests


def shape(node_id, x=0, y=0, width=60, height=40, **extra):
    node = {"id": node_id, "type": "shape", "style": {"x": x, "y": y, "width": width, "height": height, "background": "#ccd9ff"}}
    node.update(extra)
    return node


class StudioCanvasPolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = runtime_tests.StudioRuntimeBrowserTests()
        cls.fixture.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass()

    def setUp(self):
        self.fixture.setUp()
        self.page = self.fixture.page

    def tearDown(self):
        self.fixture.tearDown()

    def mount(self, nodes, **extra):
        self.fixture.mount(nodes, **extra)
        self.page.evaluate("instance.setZoom(1)")

    def rect(self, node_id):
        return self.page.locator('[data-studio-select-id="' + node_id + '"]').evaluate("el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}}")

    def commits(self):
        return self.page.evaluate("events.filter(e=>e.type==='studio-commit')")

    def select(self, *ids):
        self.page.evaluate("ids=>instance.select(ids)", list(ids))

    def drag(self, start, delta, *, alt=False):
        if alt:
            self.page.keyboard.down("Alt")
        self.page.mouse.move(*start)
        self.page.mouse.down()
        self.page.mouse.move(start[0] + delta[0], start[1] + delta[1], steps=5)
        self.page.mouse.up()
        if alt:
            self.page.keyboard.up("Alt")

    def test_six_alignment_commands_use_rendered_nested_geometry_and_undo(self):
        for command in ("left", "right", "top", "bottom", "center", "middle"):
            with self.subTest(command=command):
                parent = shape("parent", 430, 140, 220, 220, type="container", children=[shape("nested", 20, 30, 50, 80)])
                parent["style"].update(rotate=30, scaleX=1.2, scaleY=.8)
                self.mount([shape("first", 90, 90, 90, 45), parent])
                self.page.evaluate("instance.setZoom(1.7);window.before=instance.document")
                initial = {key: self.rect(key) for key in ("first", "nested")}
                self.select("first", "nested")
                self.assertTrue(self.page.evaluate("command=>instance.action('align-'+command)", command))
                left, right = self.rect("first"), self.rect("nested")
                if command in ("left", "right", "top", "bottom"):
                    self.assertAlmostEqual(left[command], right[command], delta=.06)
                else:
                    axis = ("left", "right") if command == "center" else ("top", "bottom")
                    self.assertAlmostEqual(sum(left[key] for key in axis), sum(right[key] for key in axis), delta=.1)
                commits = self.commits()
                self.assertEqual(len(commits), 1)
                self.assertTrue(all(command["type"] == "node.update" for command in commits[0]["commands"]))
                self.assertEqual({command["node_id"] for command in commits[0]["commands"]} - {"first", "nested"}, set())
                self.page.evaluate("instance.update(before,{selectedIds:['first','nested'],mode:'edit'})")
                for key, rect in initial.items():
                    self.assertAlmostEqual(self.rect(key)["left"], rect["left"], delta=.01)
                    self.assertAlmostEqual(self.rect(key)["top"], rect["top"], delta=.01)

    def test_equal_gap_distribution_preserves_endpoints_and_unequal_sizes(self):
        for axis in ("horizontal", "vertical"):
            with self.subTest(axis=axis):
                self.mount([shape("a", 50, 40, 40, 30), shape("b", 120, 140, 100, 60), shape("c", 430, 440, 70, 90)])
                self.page.evaluate("instance.setZoom(.55)")
                self.select("c", "a", "b")
                before = {key: self.rect(key) for key in ("a", "b", "c")}
                self.assertTrue(self.page.evaluate("axis=>instance.action('distribute-'+axis)", axis))
                a, b, c = [self.rect(key) for key in ("a", "b", "c")]
                start, end = ("left", "right") if axis == "horizontal" else ("top", "bottom")
                self.assertAlmostEqual(b[start] - a[end], c[start] - b[end], delta=.05)
                self.assertEqual(a, before["a"])
                self.assertEqual(c, before["c"])
                self.assertEqual(len(self.commits()), 1)
                self.assertEqual(self.commits()[0]["commands"][0]["node_id"], "b")

    def test_nudge_is_canvas_pixel_based_at_zoom_and_skips_locked_descendants(self):
        parent = shape("parent", 400, 100, 250, 250, type="container", children=[shape("child", 30, 40)])
        parent["style"].update(rotate=90, scaleX=2, scaleY=1.5)
        locked = shape("locked", 100, 100, locked=True, children=[shape("locked-child", 10, 10)])
        self.mount([parent, locked])
        self.page.evaluate("instance.setZoom(2)")
        self.select("child", "locked-child")
        before = self.rect("child")
        self.page.locator(".studio-viewport").focus()
        self.page.keyboard.press("ArrowRight")
        self.page.keyboard.press("Shift+ArrowDown")
        after = self.rect("child")
        self.assertAlmostEqual(after["left"] - before["left"], 2, delta=.05)
        self.assertAlmostEqual(after["top"] - before["top"], 20, delta=.05)
        self.assertEqual(len(self.commits()), 2)
        self.assertTrue(all(c["commands"][0]["node_id"] == "child" and len(c["commands"]) == 1 for c in self.commits()))
        self.page.keyboard.press("Control+z")
        self.assertEqual(self.page.evaluate("events.at(-1).action"), "undo")

    def test_selected_ancestor_and_descendant_move_once_and_preview_ignores_actions(self):
        self.mount([shape("parent", 100, 100, 200, 180, type="container", children=[shape("child", 20, 20)]), shape("other", 500, 250)])
        self.select("parent", "child", "other")
        self.page.locator(".studio-viewport").focus()
        self.page.keyboard.press("ArrowLeft")
        self.assertEqual({item["node_id"] for item in self.commits()[0]["commands"]}, {"parent", "other"})
        self.page.evaluate("instance.setMode('preview')")
        self.assertFalse(self.page.evaluate("instance.action('align-left')"))
        self.assertEqual(self.page.locator(".studio-selection-box").count(), 0)

    def test_marquee_selects_contained_visible_unlocked_nodes_and_shift_adds(self):
        self.mount([shape("a", 100, 100), shape("b", 230, 120), shape("locked", 150, 130, locked=True), shape("hidden", 170, 150, hidden=True), shape("c", 500, 350)])
        a, b = self.rect("a"), self.rect("b")
        self.drag((a["left"] - 15, a["top"] - 15), (b["right"] - a["left"] + 30, b["bottom"] - a["top"] + 30))
        self.assertEqual(set(self.page.evaluate("events.filter(e=>e.type==='studio-selection').at(-1).ids")), {"a", "b"})
        self.assertEqual(self.page.locator(".studio-selection-box .studio-handle").count(), 8)
        c = self.rect("c")
        self.page.keyboard.down("Shift")
        self.drag((c["left"] - 10, c["top"] - 10), (c["width"] + 20, c["height"] + 20))
        self.page.keyboard.up("Shift")
        self.assertEqual(set(self.page.evaluate("events.filter(e=>e.type==='studio-selection').at(-1).ids")), {"a", "b", "c"})
        self.assertEqual(self.page.locator(".studio-marquee").count(), 0)
        self.assertEqual(self.commits(), [])

    def test_drag_snap_guides_alt_bypass_and_escape_restore(self):
        self.mount([shape("moving", 100, 100, 40, 40), shape("reference", 240, 300, 40, 40)])
        r = self.rect("moving")
        start = (r["left"] + 20, r["top"] + 20)
        self.page.mouse.move(*start)
        self.page.mouse.down()
        self.page.mouse.move(start[0] + 97, start[1] + 70, steps=5)
        self.page.wait_for_timeout(30)
        self.assertTrue(self.page.locator(".studio-snap-guide").evaluate_all("lines=>lines.some(line=>line.style.opacity==='1')"))
        self.page.mouse.up()
        self.assertAlmostEqual(self.rect("moving")["right"], self.rect("reference")["left"], delta=.05)
        self.assertEqual(len(self.commits()), 1)
        self.assertEqual(self.page.locator(".studio-snap-guide").count(), 0)
        r = self.rect("moving")
        self.page.mouse.move(r["left"] + 20, r["top"] + 20)
        self.page.mouse.down()
        self.page.mouse.move(r["left"] + 70, r["top"] + 60)
        self.page.keyboard.press("Escape")
        self.page.mouse.up()
        self.assertAlmostEqual(self.rect("moving")["left"], r["left"], delta=.01)
        self.assertEqual(len(self.commits()), 1)
        self.mount([shape("moving", 100, 100, 40, 40), shape("reference", 240, 300, 40, 40)])
        r = self.rect("moving")
        self.drag((r["left"] + 20, r["top"] + 20), (97, 70), alt=True)
        self.assertAlmostEqual(self.rect("moving")["right"], self.rect("reference")["left"] - 3, delta=.05)

    def test_multi_resize_scales_nested_rendered_geometry_and_undoes_one_transaction(self):
        parent = shape("parent", 360, 160, 220, 200, type="container", children=[shape("nested", 25, 35, 70, 50)])
        parent["style"].update(rotate=27, scaleX=1.1, scaleY=.9)
        self.mount([shape("plain", 80, 70, 80, 50), parent])
        self.page.evaluate("instance.setZoom(.9);window.before=instance.document")
        self.select("plain", "nested")
        old = {key: self.rect(key) for key in ("plain", "nested")}
        group = self.page.locator(".studio-selection-box").bounding_box()
        grip = self.page.locator('.studio-selection-box [data-handle="se"]').bounding_box()
        dx, dy = 80, 45
        self.drag((grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2), (dx, dy))
        sx, sy = (group["width"] + dx) / group["width"], (group["height"] + dy) / group["height"]
        for key, rect in old.items():
            after = self.rect(key)
            self.assertAlmostEqual(after["left"], group["x"] + (rect["left"] - group["x"]) * sx, delta=.12)
            self.assertAlmostEqual(after["top"], group["y"] + (rect["top"] - group["y"]) * sy, delta=.12)
            self.assertAlmostEqual(after["width"], rect["width"] * sx, delta=.12)
            self.assertAlmostEqual(after["height"], rect["height"] * sy, delta=.12)
        self.assertEqual(len(self.commits()), 1)
        self.assertEqual(len(self.commits()[0]["commands"]), 2)
        self.page.evaluate("instance.update(before,{selectedIds:['plain','nested'],mode:'edit'})")
        for key, rect in old.items():
            self.assertAlmostEqual(self.rect(key)["width"], rect["width"], delta=.02)
            self.assertAlmostEqual(self.rect(key)["left"], rect["left"], delta=.02)

    def test_flow_text_doubleclick_keeps_node_target_and_does_not_reorder(self):
        for authored in (False, True):
            with self.subTest(authored=authored):
                child = {"id": "label", "type": "element" if authored else "text", "style": {"width": 140, "height": 50}, "props": {"text": "Before", **({"authored": True, "tag": "div"} if authored else {})}}
                self.mount([{"id": "row", "type": "container", "style": {"x": 100, "y": 100, "width": 400, "height": 100, "display": "flex", "gap": 20}, "children": [child, shape("sibling", width=80, height=50)]}])
                text = self.page.locator('[data-studio-node="label"]' + ('' if authored else ' > .studio-content'))
                text.dblclick()
                self.assertEqual(text.get_attribute("contenteditable"), "plaintext-only")
                self.page.keyboard.insert_text("After")
                self.page.keyboard.press("Enter")
                self.assertEqual(text.inner_text(), "After")
                self.assertEqual(len(self.commits()), 1)
                self.assertEqual(self.commits()[0]["commands"][0]["type"], "node.update")
                self.assertEqual(self.commits()[0]["commands"][0]["patch"]["props"]["text"], "After")

    def test_flow_drag_reorders_row_column_and_wrap_without_absolute_offsets(self):
        for direction, wrap in (("row", "nowrap"), ("column", "nowrap"), ("row", "wrap")):
            with self.subTest(direction=direction, wrap=wrap):
                self.mount([{"id": "flow", "type": "container", "style": {"x": 100, "y": 100, "width": 180 if wrap == "wrap" else 380, "height": 280, "display": "flex", "flexDirection": direction, "flexWrap": wrap, "gap": 12, "padding": 10}, "children": [shape("a", width=70, height=60), shape("b", width=70, height=60), shape("c", width=70, height=60)]}])
                self.page.evaluate("window.before=instance.document")
                a, c = self.rect("a"), self.rect("c")
                start = (a["left"] + a["width"] / 2, a["top"] + a["height"] / 2)
                end = (c["right"] - 4, c["top"] + c["height"] / 2) if direction == "row" else (c["left"] + c["width"] / 2, c["bottom"] - 4)
                self.drag(start, (end[0] - start[0], end[1] - start[1]))
                self.assertEqual(self.page.evaluate("instance.document.pages[0].nodes[0].children.map(n=>n.id)"), ["b", "c", "a"])
                self.assertEqual(self.commits()[0]["commands"], [{"type": "node.move", "page_id": "home", "node_id": "a", "parent_id": "flow", "index": 2}])
                self.assertEqual(self.page.locator(".studio-reorder-guide").count(), 0)
                self.page.evaluate("instance.update(before,{selectedIds:['a'],mode:'edit'})")
                self.assertEqual(self.page.evaluate("instance.document.pages[0].nodes[0].children.map(n=>n.id)"), ["a", "b", "c"])

    def test_auto_layout_fill_hug_fixed_padding_constraints_and_preview_match(self):
        nodes = [{"id": "row", "type": "container", "style": {"x": 40, "y": 40, "width": 460, "height": 100, "layout": "row", "gap": 10, "padding": 20, "alignItems": "center"}, "children": [shape("fixed", width=80, height=30), {"id": "fill", "type": "text", "style": {"widthMode": "fill", "height": 30, "minWidth": 100, "maxWidth": 300}, "props": {"text": "Fill"}}]}, {"id": "hug", "type": "container", "style": {"x": 40, "y": 200, "widthMode": "hug", "heightMode": "hug", "layout": "row", "padding": 12, "gap": 8}, "children": [shape("hug-a", width=60, height=30), shape("hug-b", width=80, height=50)]}]
        self.mount(nodes)
        self.assertAlmostEqual(self.rect("fixed")["width"], 80, delta=.01)
        self.assertAlmostEqual(self.rect("fill")["width"], 300, delta=.01)
        self.assertAlmostEqual(self.rect("hug")["width"], 172, delta=.01)
        self.assertAlmostEqual(self.rect("hug")["height"], 74, delta=.01)
        self.assertAlmostEqual(self.rect("fill")["left"] - self.rect("fixed")["right"], 10, delta=.01)
        edit = {key: self.rect(key) for key in ("row", "fixed", "fill", "hug")}
        self.page.evaluate("instance.setMode('preview');instance.setZoom(1)")
        for key, rect in edit.items():
            self.assertAlmostEqual(self.rect(key)["width"], rect["width"], delta=.01)
            self.assertAlmostEqual(self.rect(key)["height"], rect["height"], delta=.01)

    def test_auto_layout_mode_changes_rebuild_flow_and_reset_stale_sizing(self):
        self.mount([{"id": "row", "type": "container", "style": {"width": 400, "height": 200, "display": "flex", "flexDirection": "row", "padding": 20}, "children": [{"id": "child", "type": "shape", "style": {"width": 80, "height": 40, "widthMode": "fill"}}]}])
        self.assertAlmostEqual(self.rect("child")["width"], 360, delta=.01)
        self.page.evaluate("""() => {const d=instance.document;d.pages[0].nodes[0].children[0].style.widthMode='fixed';instance.update(d,{mode:'edit'});} """)
        self.assertAlmostEqual(self.rect("child")["width"], 80, delta=.01)
        self.page.evaluate("""() => {const d=instance.document;d.pages[0].nodes[0].style.display='block';d.pages[0].nodes[0].children[0].style.x=35;instance.update(d,{mode:'edit'});} """)
        self.assertEqual(self.page.locator('[data-studio-node="child"]').evaluate("el=>getComputedStyle(el).position"), "absolute")
        self.assertAlmostEqual(self.rect("child")["left"] - self.rect("row")["left"], 35, delta=.01)

    def test_shared_style_references_order_and_component_overrides_render(self):
        styles = {"legacy": {"style": {"color": "red", "fontSize": 12}}, "type": {"kind": "typography", "style": {"fontSize": 20, "color": "blue"}}, "space": {"kind": "spacing", "style": {"padding": 9}}}
        self.mount([{"id": "text", "type": "text", "props": {"text": "Styled", "styleId": "legacy", "styleIds": ["type", "space"]}, "style": {"color": "green"}}], styles=styles)
        visual = self.page.locator('[data-studio-node="text"] .studio-content')
        self.assertEqual(visual.evaluate("el=>getComputedStyle(el).color"), "rgb(0, 128, 0)")
        self.assertEqual(visual.evaluate("el=>getComputedStyle(el).fontSize"), "20px")
        self.assertEqual(visual.evaluate("el=>getComputedStyle(el).padding"), "9px")
        self.page.evaluate("""() => {const d=instance.document;d.pages[0].nodes[0].props.styleIds=[];instance.update(d,{mode:'edit'});} """)
        self.assertEqual(visual.evaluate("el=>getComputedStyle(el).fontSize"), "12px")
        self.assertEqual(visual.evaluate("el=>getComputedStyle(el).padding"), "0px")

    def test_cross_axis_fill_stretches_centered_column_and_row(self):
        for direction, axis, size in (("column", "width", 260), ("row", "height", 160)):
            for align in ("center", "flex-start"):
                with self.subTest(direction=direction, align=align):
                    child = shape("child", width=60, height=40)
                    child["style"][axis + "Mode"] = "fill"
                    self.mount([{"id": "parent", "type": "container", "style": {"width": 300, "height": 200, "display": "flex", "flexDirection": direction, "alignItems": align, "padding": 20}, "children": [child]}])
                    self.assertAlmostEqual(self.rect("child")[axis], size, delta=.01)
                    self.assertEqual(self.page.locator('[data-studio-node="child"]').evaluate("el=>getComputedStyle(el).alignSelf"), "stretch")

    def test_authored_flex_cross_axis_fill_uses_computed_parent_layout(self):
        self.mount([{"id": "authored-parent", "type": "element", "props": {"authored": True, "tag": "section", "attributes": {"style": "display:flex;flex-direction:column;align-items:center;padding:10px;width:300px;height:160px"}}, "children": [{"id": "authored-child", "type": "element", "props": {"authored": True, "tag": "div", "text": "Fill", "attributes": {"style": "width:60px;height:40px"}}, "style": {"widthMode": "fill", "alignSelf": "center"}}]}])
        self.assertAlmostEqual(self.rect("authored-child")["width"], 280, delta=.01)
        self.assertEqual(self.page.locator('[data-studio-node="authored-child"]').evaluate("el=>getComputedStyle(el).alignSelf"), "stretch")
        self.page.evaluate("""() => {const d=instance.document;d.pages[0].nodes[0].children[0].style.color='red';instance.update(d,{mode:'edit'});} """)
        self.assertAlmostEqual(self.rect("authored-child")["width"], 280, delta=.01)
        self.assertEqual(self.page.locator('[data-studio-node="authored-child"]').evaluate("el=>getComputedStyle(el).alignSelf"), "stretch")
        self.page.evaluate("instance.setMode('preview');instance.setZoom(1)")
        self.assertAlmostEqual(self.rect("authored-child")["width"], 280, delta=.01)

    def test_authored_hug_preserves_unrelated_inline_flex_constraints_and_margins(self):
        self.mount([{"id": "parent", "type": "element", "props": {"authored": True, "tag": "section", "attributes": {"style": "display:flex;width:500px;height:180px"}}, "children": [{"id": "child", "type": "element", "props": {"authored": True, "tag": "div", "text": "Content", "attributes": {"style": "flex:1;min-width:120px;max-width:250px;margin:10px"}}, "style": {"heightMode": "hug"}}]}])
        child = self.page.locator('[data-studio-node="child"]')
        values = child.evaluate("el=>{const s=getComputedStyle(el);return [s.flexGrow,s.flexShrink,s.minWidth,s.maxWidth,s.margin]}")
        self.assertEqual(values, ["1", "1", "120px", "250px", "10px"])
        self.page.evaluate("""() => {const d=instance.document;d.pages[0].nodes[0].children[0].style={};instance.update(d,{mode:'edit'});} """)
        self.assertEqual(child.evaluate("el=>{const s=getComputedStyle(el);return [s.flexGrow,s.flexShrink,s.minWidth,s.maxWidth,s.margin]}"), values)

    def test_center_origin_native_resize_retains_opposite_corner(self):
        node = shape("rotated", 200, 180, 100, 60)
        node["style"].update(rotate=90, transformOrigin="50% 50%")
        self.mount([node])
        self.page.evaluate("instance.setZoom(.7)")
        self.select("rotated")
        before = self.rect("rotated")
        grip = self.page.locator('[data-studio-node="rotated"] > [data-handle="e"]').bounding_box()
        self.drag((grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2), (0, 28))
        after = self.rect("rotated")
        self.assertAlmostEqual(after["right"], before["right"], delta=.05)
        self.assertAlmostEqual(after["top"], before["top"], delta=.05)
        self.assertAlmostEqual(after["height"], before["height"] + 28, delta=.05)
        self.assertEqual(len(self.commits()), 1)

    def test_rotated_authored_center_origin_resize_and_cancel(self):
        self.mount([{"id": "authored", "type": "element", "props": {"authored": True, "tag": "section", "text": "Resizable", "attributes": {"style": "position:absolute;left:180px;top:150px;width:100px;height:60px;transform:rotate(25deg);transform-origin:50% 50%"}}}])
        self.select("authored")
        before = self.rect("authored")
        grip = self.page.locator('.studio-selection-box [data-handle="se"]').bounding_box()
        self.drag((grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2), (60, 35))
        after = self.rect("authored")
        self.assertAlmostEqual(after["left"], before["left"], delta=.08)
        self.assertAlmostEqual(after["top"], before["top"], delta=.08)
        self.assertAlmostEqual(after["width"], before["width"] + 60, delta=.08)
        self.assertAlmostEqual(after["height"], before["height"] + 35, delta=.08)
        self.assertEqual(len(self.commits()), 1)
        grip = self.page.locator('.studio-selection-box [data-handle="se"]').bounding_box()
        self.page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
        self.page.mouse.down()
        self.page.mouse.move(grip["x"] + 40, grip["y"] + 30)
        self.page.keyboard.press("Escape")
        self.page.mouse.up()
        self.assertAlmostEqual(self.rect("authored")["width"], after["width"], delta=.02)
        self.assertEqual(len(self.commits()), 1)

    def test_hug_component_instance_and_keyed_and_legacy_props_overrides(self):
        components = {"card": {"node": {"id": "master", "type": "container", "style": {"layout": "row", "widthMode": "hug", "heightMode": "hug", "padding": 10, "gap": 8}, "children": [{"id": "label", "type": "text", "props": {"text": "Default", "styleIds": ["type"]}, "style": {"width": 80, "height": 30}}]}}, "button": {"node": {"id": "button-root", "type": "button", "props": {"text": "Original"}, "style": {"width": 100, "height": 40}}}}
        self.mount([{"id": "instance", "type": "instance", "style": {"widthMode": "hug", "heightMode": "hug"}, "props": {"componentId": "card", "overrides": {"label": {"props": {"text": "Overridden"}, "style": {"color": "green"}}}}}, {"id": "legacy", "type": "instance", "style": {"x": 250, "width": 130, "height": 50}, "props": {"componentId": "button", "overrides": {"text": "Legacy", "disabled": True, "state": "busy"}}}], components=components, styles={"type": {"style": {"fontSize": 19, "color": "blue"}}})
        self.assertAlmostEqual(self.rect("instance")["width"], 100, delta=.01)
        self.assertAlmostEqual(self.rect("instance")["height"], 50, delta=.01)
        label = self.page.locator('[data-studio-node="label"] .studio-content')
        self.assertEqual(label.inner_text(), "Overridden")
        self.assertEqual(label.evaluate("el=>getComputedStyle(el).color"), "rgb(0, 128, 0)")
        self.assertEqual(label.evaluate("el=>getComputedStyle(el).fontSize"), "19px")
        button = self.page.locator('[data-studio-node="button-root"] button')
        self.assertEqual(button.inner_text(), "Legacy")
        self.assertTrue(button.is_disabled())
        self.assertEqual(button.get_attribute("data-state"), "busy")
        self.page.evaluate("instance.setMode('preview');instance.setZoom(1)")
        self.assertAlmostEqual(self.rect("instance")["width"], 100, delta=.01)
        self.assertTrue(button.is_disabled())

    def test_disabled_state_and_alt_apply_incrementally_and_in_preview(self):
        nodes = [{"id": "button", "type": "button", "style": {"x": 100, "y": 100, "width": 120, "height": 40}, "props": {"text": "Go", "disabled": True, "state": "busy", "navigateTo": "other"}}, {"id": "image", "type": "image", "style": {"x": 300, "width": 80, "height": 60}, "props": {"src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'/>", "alt": "Before"}}, {"id": "authored-image", "type": "element", "props": {"authored": True, "tag": "img", "attributes": {"alt": "Authored fallback"}, "alt": "Explicit alt"}}]
        self.mount([], pages=[{"id": "home", "width": 800, "height": 600, "nodes": nodes}, {"id": "other", "width": 800, "height": 600, "nodes": []}])
        button = self.page.locator('[data-studio-node="button"] button')
        self.assertTrue(button.is_disabled())
        self.assertEqual(button.get_attribute("data-state"), "busy")
        self.assertEqual(self.page.locator('[data-studio-node="authored-image"]').get_attribute("alt"), "Explicit alt")
        self.page.evaluate("instance.setMode('preview')")
        button.dispatch_event("click")
        self.assertFalse(self.page.evaluate("events.some(e=>e.type==='studio-navigate')"))
        self.page.evaluate("""() => {instance.setMode('edit');const d=instance.document;d.pages[0].nodes[0].props.disabled=false;d.pages[0].nodes[0].props.state='ready';d.pages[0].nodes[1].props.alt='After';d.pages[0].nodes[2].props.alt='Changed authored';instance.update(d,{mode:'edit'});} """)
        self.assertFalse(button.is_disabled())
        self.assertEqual(button.get_attribute("data-state"), "ready")
        self.assertEqual(self.page.locator('[data-studio-node="image"] img').get_attribute("alt"), "After")
        self.assertEqual(self.page.locator('[data-studio-node="authored-image"]').get_attribute("alt"), "Changed authored")
        self.page.evaluate("instance.setMode('preview')")
        button.click()
        self.assertTrue(self.page.evaluate("events.some(e=>e.type==='studio-navigate'&&e.pageId==='other')"))

    def test_bridge_actions_require_matching_source_origin_and_session(self):
        context = self.fixture.browser.new_context()
        runtime = runtime_tests.RUNTIME
        host = '<script>window.events=[];addEventListener("message", e=>events.push(e.data));</script><iframe id="canvas" src="https://studio.test/runtime.html?session=secret&parentOrigin=https%3A%2F%2Fparent.test"></iframe>'

        def route(request):
            url = urlparse(request.request.url)
            if url.hostname == "parent.test":
                request.fulfill(body=host, content_type="text/html")
            elif url.path.endswith("runtime.js"):
                request.fulfill(body=(runtime / "runtime.js").read_text(), content_type="text/javascript")
            elif url.path.endswith("runtime.css"):
                request.fulfill(body=(runtime / "runtime.css").read_text(), content_type="text/css")
            else:
                request.fulfill(body=(runtime / "runtime.html").read_text(), content_type="text/html")

        context.route("**/*", route)
        page = context.new_page()
        try:
            page.goto("https://parent.test/")
            page.wait_for_function("events.some(e=>e.type==='studio-ready')")
            document = {"id": "bridge", "pages": [{"id": "home", "width": 800, "height": 600, "nodes": [shape("a", 40, 80), shape("b", 250, 220)]}]}
            page.evaluate("document=>canvas.contentWindow.postMessage({type:'studio-init',session:'secret',document,selectedIds:['a','b']},'https://studio.test')", document)
            page.wait_for_function("events.some(e=>e.type==='studio-rendered')")
            page.evaluate("canvas.contentWindow.postMessage({type:'studio-action',action:'align-left',session:'wrong'},'https://studio.test')")
            page.wait_for_timeout(30)
            self.assertFalse(page.evaluate("events.some(e=>e.type==='studio-commit')"))
            page.evaluate("canvas.contentWindow.postMessage({type:'studio-action',action:'align-left',session:'secret'},'https://studio.test')")
            page.wait_for_function("events.some(e=>e.type==='studio-commit')")
            self.assertEqual(page.evaluate("events.find(e=>e.type==='studio-commit').commands[0].node_id"), "b")
        finally:
            context.close()


class StudioCanvasGeometryTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required for renderer math contracts")
    def test_runtime_affine_resize_and_sizing_helpers(self):
        # Execute the production functions independently of browser availability.
        script = r"""const fs=require('fs'), vm=require('vm'), assert=require('assert');
const source=fs.readFileSync('vault_rag/design_assets/studio/runtime.js','utf8');
class Matrix {
 constructor(v=[1,0,0,1,0,0]){[this.a,this.b,this.c,this.d,this.e,this.f]=v;}
 multiply(r){return new Matrix([this.a*r.a+this.c*r.b,this.b*r.a+this.d*r.b,this.a*r.c+this.c*r.d,this.b*r.c+this.d*r.d,this.a*r.e+this.c*r.f+this.e,this.b*r.e+this.d*r.f+this.f]);}
 inverse(){let det=this.a*this.d-this.b*this.c;return new Matrix([this.d/det,-this.b/det,-this.c/det,this.a/det,(this.c*this.f-this.d*this.e)/det,(this.b*this.e-this.a*this.f)/det]);}
 scale(x,y=x){return this.multiply(new Matrix([x,0,0,y,0,0]));}
 translate(x,y){return this.multiply(new Matrix([1,0,0,1,x,y]));}
 rotate(deg){let r=deg*Math.PI/180;return this.multiply(new Matrix([Math.cos(r),Math.sin(r),-Math.sin(r),Math.cos(r),0,0]));}
 point(x,y){return [this.a*x+this.c*y+this.e,this.b*x+this.d*y+this.f];}
}
const rounded=x=>Math.round(x*100)/100;
const context={win:{DOMMatrix:Matrix},rounded,movePatch:(t,dx,dy)=>{let d=t.convert(dx,dy);return{x:rounded(t.startX+d.x),y:rounded(t.startY+d.y)}}};
vm.createContext(context);vm.runInContext(source.slice(source.indexOf('    function groupResizePatch('),source.indexOf('    function updateGesture(')),context);
const rect=(m,w,h)=>{const points=[[0,0],[w,0],[0,h],[w,h]].map(p=>m.point(...p));let left=Math.min(...points.map(p=>p[0])),top=Math.min(...points.map(p=>p[1])),right=Math.max(...points.map(p=>p[0])),bottom=Math.max(...points.map(p=>p[1]));return {left,top,right,bottom,width:right-left,height:bottom-top};};
let checks=0,maxError=0;
for(let i=0;i<1000;i++){
 const p=new Matrix().translate(-170,210).rotate(i*17%360).scale(.25+(i%20)/10,.3+(i%13)/10);
 const t=new Matrix().rotate(i*31%360).scale(.5+(i%8)/10,.8+(i%11)/10).translate(i%15,i%9);
 const w=50+i%50,h=40+i%60,x=20+i%30,y=35+i%25,origin=[w*.5,h*.5];
 const actual=p.translate(x+origin[0],y+origin[1]).multiply(t).translate(-origin[0],-origin[1]);
 const r=rect(actual,w,h),bounds={left:r.left-50,top:r.top-60,width:r.width+100,height:r.height+120};
 const sx=.6+(i%10)/5,sy=.7+(i%9)/5,box={left:bounds.left-20,top:bounds.top+30,width:bounds.width*sx,height:bounds.height*sy};
 const inv=p.inverse(), target={matrix:p.multiply(t),parentMatrix:p,width:w,height:h,rect:r,startX:x,startY:y,origin,entry:{authored:i%2===0},display:'block',convert:(x,y)=>({x:inv.a*x+inv.c*y,y:inv.b*x+inv.d*y})};
 const patch=context.groupResizePatch(target,{bounds},box), v=patch.transform.slice(7,-1).split(',').map(Number), out=p.translate(patch.x,patch.y).multiply(new Matrix(v));
 const expected=new Matrix().translate(box.left,box.top).scale(sx,sy).translate(-bounds.left,-bounds.top).multiply(actual);
 const a=rect(out,patch.width,patch.height),b=rect(expected,w,h);
 for(const key of ['left','top','right','bottom']){const error=Math.abs(a[key]-b[key]);maxError=Math.max(maxError,error);assert(error<.08,JSON.stringify({i,key,error,patch,a,b}));checks++;}
}
// Exact runtime sizing function: defaults and authored CSS preservation.
const sizingContext={win:{getComputedStyle:el=>el.computed},cssValue:(key,v)=>typeof v==='number'?v+'px':String(v),outerKeys:new Set(['flex','flexGrow','flexShrink','flexBasis','alignSelf','margin']),inFlow:()=>true};
vm.createContext(sizingContext);vm.runInContext(source.slice(source.indexOf('    function applySizing('),source.indexOf('    function applyLayout(')),sizingContext);
let el={style:{},parentElement:{computed:{display:'flex',flexDirection:'column'}}},entry={wrapper:el,visual:{style:{}},flow:true};sizingContext.applySizing(entry,{widthMode:'fill'});assert.equal(el.style.alignSelf,'stretch');assert.equal(el.style.width,'auto');assert.equal(el.style.minWidth,'0px');
el={style:{flex:'1',minWidth:'120px',margin:'10px'},parentElement:{computed:{display:'flex',flexDirection:'row'}}};entry={wrapper:el,visual:el,authored:true};sizingContext.applySizing(entry,{heightMode:'hug'});assert.equal(el.style.flex,'1');assert.equal(el.style.minWidth,'120px');assert.equal(el.style.margin,'10px');
console.log(JSON.stringify({affineChecks:checks,maxPixelError:maxError,sizingContracts:2}));
"""
        result = subprocess.run(["node", "-e", script], cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True, check=True)
        report = json.loads(result.stdout)
        self.assertEqual(report["affineChecks"], 4000)
        self.assertLess(report["maxPixelError"], .08)
        self.assertEqual(report["sizingContracts"], 2)


if __name__ == "__main__":
    unittest.main()
