"""Explicit isolated legacy conversion and performance acceptance.

Usage: python tests/studio_migration_acceptance.py --source /path/to/project
Only a temporary copy is served or changed; evidence stays under .cache/studio-qa.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import statistics
import sys
import tempfile
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright


def digest_tree(path):
    digest = hashlib.sha256()
    for p in sorted(path.rglob('*')):
        if p.is_file() and not p.is_symlink():
            digest.update(p.relative_to(path).as_posix().encode())
            with p.open('rb') as stream:
                digest.update(hashlib.file_digest(stream, 'sha256').digest())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    args = parser.parse_args()
    source = Path(args.source).resolve()
    before = digest_tree(source)
    evidence = Path(__file__).resolve().parents[1] / '.cache/studio-qa'
    evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='leafloom-studio-acceptance-') as temp:
        home = Path(temp).resolve(); root = home / 'vault'; root.mkdir()
        shutil.copytree(source, root / 'Legacy', ignore=shutil.ignore_patterns('.git', '.vault-rag', '.DS_Store'))
        with socket.socket() as port_socket:
            port_socket.bind(('127.0.0.1', 0)); port = port_socket.getsockname()[1]
        repository = Path(__file__).resolve().parents[1]
        server_log = (home / 'server.log').open('w')
        server = subprocess.Popen([str(repository / '.venv/bin/python'), str(repository / 'tests/html_projects_server.py'),
                                   '--directory', str(home), '--port', str(port)], stdout=server_log, stderr=server_log)
        base = f'http://127.0.0.1:{port}'
        token = ''
        def api(endpoint, body=None):
            request = Request(base + '/api/design/' + endpoint, data=json.dumps({'root': str(root), **body}).encode() if body is not None else None,
                              headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
            try:
                with urlopen(request) as response:
                    return json.load(response)
            except HTTPError as error:
                raise AssertionError(endpoint + ': ' + error.read().decode()) from error
        for _ in range(100):
            try:
                urlopen(base + '/healthz').close(); break
            except OSError:
                time.sleep(.1)
        token = (home / 'state/auth-token').read_text().strip()
        ui_origin = json.loads((home / 'info.json').read_text())['ui']
        browser = None
        try:
            with sync_playwright() as playwright:
                executable = Path(playwright.chromium.executable_path)
                if not executable.exists(): executable = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
                if os.environ.get('LEAFLOOM_BROWSER_EXECUTABLE'): executable = Path(os.environ['LEAFLOOM_BROWSER_EXECUTABLE'])
                browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
                page = browser.new_page(viewport={'width': 1200, 'height': 1800})
                diagnostics = []
                page.on('pageerror', lambda error: diagnostics.append({'type': 'pageerror', 'message': str(error)}))
                page.on('response', lambda response: diagnostics.append({'type': 'http', 'status': response.status, 'url': response.url}) if response.status >= 400 else None)
                page.goto(ui_origin + '/healthz')
                # Establish whether the current legacy project already fails,
                # using only the disposable copy before conversion repairs it.
                legacy_session = api('session', {'directory': 'Legacy', 'capture': True})
                legacy_url = legacy_session['origin'] + '/Design/studio/capture.html?' + urlencode({'session': legacy_session['id'], 'parentOrigin': ui_origin})
                page.evaluate('''url=>{const frame=document.createElement('iframe');frame.id='preflight';frame.src=url;frame.style='width:800px;height:1700px;border:0';document.body.replaceChildren(frame);}''', legacy_url)
                preflight = page.locator('#preflight').content_frame
                preflight.locator('#source').evaluate("frame=>{frame.style.width='720px';frame.style.height='1560px';frame.src='/Design/UI/Site/screen.html?id=home'}")
                legacy_original = preflight.locator('#source').content_frame
                legacy_original.locator('#artboard').wait_for(state='attached')
                page.wait_for_timeout(200)
                original_preexisting_errors = [entry['message'] for entry in diagnostics if entry['type'] == 'pageerror']
                if original_preexisting_errors:
                    print('Preexisting legacy errors: ' + '; '.join(original_preexisting_errors), flush=True)
                legacy_original.locator('#artboard').screenshot(path=str(evidence / 'original-current-home.png'), animations='disabled')
                migrated = api('migrate', {'directory': 'Legacy', 'destination': 'Converted'})
                print('Copy prepared; capturing authored artboards', flush=True)
                session = migrated['session']
                frame_url = session['origin'] + '/Design/studio/capture.html?' + urlencode({'session': session['id'], 'parentOrigin': ui_origin})
                page.evaluate('''({url,session,boards,entry})=>{
                  window.captureResult=null;window.captureFailure=null;window.captured=0;
                  const frame=document.createElement('iframe');frame.id='capture';frame.style='width:800px;height:1700px;border:0';
                  addEventListener('message',event=>{if(event.source!==frame.contentWindow||event.data?.session!==session)return;
                    if(event.data.type==='studio-capture-ready')frame.contentWindow.postMessage({type:'studio-capture-init',session,boards,entry},new URL(url).origin);
                    if(event.data.type==='studio-capture-complete')window.captureResult=event.data.pages;
                    if(event.data.type==='studio-capture-progress')window.captured++;
                    if(event.data.type==='studio-capture-error')window.captureFailure=event.data.message;
                  });frame.src=url;document.body.replaceChildren(frame);
                }''', {'url': frame_url, 'session': session['id'], 'boards': migrated['document']['migration']['boards'], 'entry': migrated['document']['migration']['entry']})
                deadline = time.monotonic() + 180
                while not page.evaluate('()=>window.captureResult||window.captureFailure'):
                    if time.monotonic() > deadline: raise AssertionError('Legacy capture did not finish')
                    page.wait_for_timeout(100)
                failure = page.evaluate('captureFailure')
                if failure: raise AssertionError(failure)
                pages = page.evaluate('captureResult')
                print(f'Captured {len(pages)} authored pages', flush=True)
                value = api('migrate/finish', {'directory': 'Converted', 'pages': pages, 'expected_revision': migrated['revision'], 'operation_id': 'finish-reference-capture'})
                (evidence / 'converted-document.json').write_text(json.dumps(value['document'],ensure_ascii=False))
                capture_frame = page.locator('#capture').content_frame
                capture_frame.locator('#source').evaluate("frame=>{frame.style.width='720px';frame.style.height='1560px';frame.src='/Design/UI/Site/screen.html?id=home'}")
                original = capture_frame.locator('#source').content_frame
                try:
                    original.locator('#artboard .home-dock').wait_for(timeout=10000)
                except Exception:
                    state = page.evaluate('''()=>[...document.querySelectorAll('iframe')].map(frame=>({src:frame.src}))''')
                    frames = [{'url': item.url, 'body': item.content()[:5000]} for item in page.frames]
                    (evidence / 'migration-failure.json').write_text(json.dumps({'state': state, 'frames': frames, 'diagnostics': diagnostics}, ensure_ascii=False, indent=2))
                    page.screenshot(path=str(evidence / 'migration-failure.png'))
                    raise
                original.locator('#artboard').screenshot(path=str(evidence / 'repaired-legacy-home.png'), animations='disabled')
                game_page = next(item for item in pages if item['id'] == 'game')
                capture_frame.locator('#source').evaluate("(frame,{width,height})=>{frame.style.width=width+'px';frame.style.height=height+'px';frame.src='/Design/UI/Site/screen.html?id=game'}", {'width': game_page['width'], 'height': game_page['height']})
                original.locator('#artboard.game .board-scene').wait_for()
                wait_artwork(original)
                original.locator('#artboard').screenshot(path=str(evidence / 'repaired-legacy-game.png'), animations='disabled')
                session = api('session', {'directory': 'Converted'})
                url = session['origin'] + '/Design/studio/runtime.html?' + urlencode({'session': session['id'], 'parentOrigin': ui_origin})
                page.evaluate('''({url,session,document:model,assetBase})=>{
                  const frame=window.runtimeFrame=document.createElement('iframe');frame.id='runtime';frame.style='width:768px;height:1608px;border:0';
                  window.runtimeMessages=[];window.runtimeInit={type:'studio-init',session,document:model,pageId:'home',mode:'edit',assetBase,selectedIds:[]};
                  addEventListener('message',event=>{if(event.source!==frame.contentWindow||event.data?.session!==session)return;runtimeMessages.push(event.data);if(event.data.type==='studio-ready')frame.contentWindow.postMessage(runtimeInit,new URL(url).origin);});
                  frame.src=url;document.body.replaceChildren(frame);
                }''', {'url': url, 'session': session['id'], 'document': value['document'], 'assetBase': session['origin'] + '/'})
                rendered = page.locator('#runtime').content_frame
                rendered.locator('.home-dock').wait_for()
                rendered.locator('img').evaluate_all('(images)=>Promise.allSettled(images.map(image=>image.decode()))')
                rendered.locator('.studio-stage').screenshot(path=str(evidence / 'converted-home.png'), animations='disabled')
                image_state = rendered.locator('img').evaluate_all('(images)=>images.filter(i=>i.src&&!i.src.startsWith("data:")).map(i=>({loaded:i.complete&&i.naturalWidth>0,source:i.getAttribute("src")}))')
                assert all(i['loaded'] for i in image_state), image_state
                assert rendered.locator('.brand-logo').count() == 1
                assert rendered.locator('.home-companion-group').count() == 1
                page.evaluate("()=>{runtimeInit.pageId='game';runtimeFrame.contentWindow.postMessage(runtimeInit,new URL(runtimeFrame.src).origin)}")
                rendered.locator('.artboard.game .board-scene').wait_for()
                wait_artwork(rendered)
                rendered.locator('.studio-stage').screenshot(path=str(evidence / 'converted-game.png'), animations='disabled')
                # Preserve the reference's two real handlers: page navigation
                # with settings source context, and accessible switch toggles.
                page.evaluate("()=>{runtimeInit.mode='preview';runtimeFrame.contentWindow.postMessage(runtimeInit,new URL(runtimeFrame.src).origin)}")
                rendered.locator('.artboard.game .game-settings').click()
                rendered.locator('.settings-modal').wait_for()
                assert rendered.locator('.artboard.settings.game-scene').count() == 1
                assert rendered.locator('.artboard.settings .home-hero').count() == 0
                switches = rendered.locator('.settings-modal [role=switch]')
                assert switches.count() == 3
                switches.first.click()
                assert switches.first.get_attribute('aria-checked') == 'false'
                assert 'on' not in switches.first.get_attribute('class').split()
                switches.first.click()
                assert switches.first.get_attribute('aria-checked') == 'true'
                rendered.locator('.settings-modal [data-target=help]').click()
                rendered.locator('.artboard.help.game-scene').wait_for()
                assert rendered.get_by_role('heading', name='当前线索', exact=True).count() == 1
                rendered.locator('.help-modal button.close').click()
                rendered.locator('.settings-modal button.close').click()
                rendered.locator('.artboard.game').wait_for()
                rendered.locator('.artboard.game button.pause').click()
                rendered.locator('.artboard.pause').wait_for()
                rendered.locator('.modal [data-target=settings][data-source=pause]').click()
                rendered.locator('.artboard.settings.game-scene').wait_for()
                rendered.locator('.settings-modal button.close').click()
                rendered.locator('.artboard.pause').wait_for()
                page.evaluate("()=>{runtimeInit.pageId='home';runtimeFrame.contentWindow.postMessage(runtimeInit,new URL(runtimeFrame.src).origin)}")
                rendered.locator('.home-settings').click()
                assert rendered.locator('.artboard.settings .home-hero').count() == 1
                rendered.locator('.settings-modal [data-target=help]').click()
                rendered.locator('.artboard.help .home-hero').wait_for()
                assert rendered.get_by_role('heading', name='当前线索', exact=True).count() == 0
                rendered.locator('.help-modal button.close').click()
                rendered.locator('.settings-modal .soft-button.primary').click()
                rendered.locator('.artboard.home').wait_for()
                runtime_errors = page.evaluate("runtimeMessages.filter(item=>item.type==='studio-error')")
                assert not runtime_errors, runtime_errors
                page.evaluate("()=>{runtimeInit.pageId='home';runtimeInit.mode='edit';runtimeFrame.contentWindow.postMessage(runtimeInit,new URL(runtimeFrame.src).origin)}")
                # This fresh page loads the production application, project home
                # and managed editor, rather than timing the renderer in isolation.
                cold = browser.new_page(viewport={'width': 1720, 'height': 1150}, locale='zh-CN')
                cold.add_init_script("localStorage.setItem('leafloom-locale','zh-CN')")
                cold_started = time.perf_counter()
                cold.goto(ui_origin)
                cold.locator('.sidebar').get_by_role('button', name='设计工作台', exact=True).click()
                cold.locator('.design-project-card').filter(has_text='Converted').locator('.design-project-title').click()
                cold.frame_locator('.dw-runtime').locator('.home-dock').wait_for()
                cold_app_to_editable_ms = (time.perf_counter() - cold_started) * 1000
                cold_document_bytes = cold.evaluate("()=>performance.getEntriesByType('resource').filter(entry=>entry.name.includes('/api/design/document?')).map(entry=>entry.decodedBodySize)")
                cold.close()
                # Warm transitions include bridge, rendering and the next paint.
                durations = []
                for target in ['game', 'collection', 'settings', 'home'] * 5:
                    started = time.perf_counter()
                    page.evaluate('(target)=>{runtimeInit.pageId=target;runtimeFrame.contentWindow.postMessage(runtimeInit,new URL(runtimeFrame.src).origin)}', target)
                    rendered.locator('.artboard.' + target).wait_for(timeout=5000)
                    durations.append((time.perf_counter() - started) * 1000)
                exported = api('export', {'directory': 'Converted'})
                offline = browser.new_page(viewport={'width': 768, 'height': 1608})
                export_dir = (root / exported['path']).with_suffix('')
                offline.goto((export_dir / 'index.html').as_uri())
                offline.locator('.home-dock').wait_for()
                assert offline.locator('.brand-logo').evaluate('(image)=>image.complete&&image.naturalWidth>0')
                offline.locator('.home-settings').click()
                offline_switch = offline.locator('.settings-modal [role=switch]').first
                offline_switch.click()
                assert offline_switch.get_attribute('aria-checked') == 'false'
                offline.locator('.settings-modal .soft-button.primary').click()
                offline.locator('.artboard.home').wait_for()
                report = {'pages': len(pages), 'source_pages': len(migrated['document']['migration']['boards']),
                          'context_variants': sum(bool(item.get('migration', {}).get('contextSource')) for item in pages),
                          'assets': len(value['document']['assets']),
                          'original_preexisting_errors': original_preexisting_errors,
                          'copy_repairs': value['document'].get('migration', {}).get('recovery', []),
                          'page_warnings': {p['id']:p['migration']['warnings'] for p in pages if p.get('migration',{}).get('warnings')},
                          'visual_baseline': 'repaired-legacy-home.png',
                          'game_visual_baseline': 'repaired-legacy-game.png',
                          'legacy_interactions': {'settings_switches': 3, 'toggle_roundtrip': True, 'settings_return_from_game': True, 'settings_return_from_pause': True, 'home_help_settings_return': True, 'settings_game_background': True, 'settings_home_background': True, 'help_context_content': True, 'offline_switch_navigation': True},
                          'authored_nodes': sum(1 for p in pages for _ in walk(p['nodes'])),
                          'sample_image_resources': len(image_state), 'offline_export': True,
                          'cold_app_to_editable_ms': cold_app_to_editable_ms,
                          'cold_document_bytes': cold_document_bytes,
                          'page_switch_ms_p95': sorted(durations)[int(len(durations)*.95)-1],
                          'page_switch_ms_median': statistics.median(durations), 'source_unchanged': digest_tree(source) == before,
                          'note': 'Local Chromium evidence; timings include browser automation overhead, not a certified cross-platform budget.'}
                assert report['source_unchanged']
                try:
                    from PIL import Image, ImageChops, ImageStat
                except ImportError:
                    report['visual_pixel_comparison'] = {'available': False, 'reason': 'Pillow is not installed; inspect saved screenshots'}
                else:
                    for key, native_name, converted_name, difference_name in (
                        ('visual_pixel_comparison', 'repaired-legacy-home.png', 'converted-home.png', 'migration-difference.png'),
                        ('game_visual_pixel_comparison', 'repaired-legacy-game.png', 'converted-game.png', 'migration-game-difference.png'),
                    ):
                        baseline = Image.open(evidence / native_name).convert('RGB')
                        converted = Image.open(evidence / converted_name).convert('RGB')
                        assert baseline.size == converted.size, (key, baseline.size, converted.size)
                        difference = ImageChops.difference(baseline, converted)
                        red, green, blue = difference.split()
                        maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
                        mask = maximum.point(lambda value: 255 if value > 16 else 0)
                        comparison = {'same_dimensions': True, 'mean_absolute_error_255': sum(ImageStat.Stat(difference).mean) / 3,
                                      'pixels_difference_gt_16_fraction': mask.histogram()[255] / (baseline.width * baseline.height)}
                        report[key] = comparison
                        difference.save(evidence / difference_name)
                        assert comparison['mean_absolute_error_255'] < 1 and comparison['pixels_difference_gt_16_fraction'] < .01, (key, comparison)
                (evidence / 'migration-report.json').write_text(json.dumps(report, indent=2))
                print(json.dumps(report, indent=2), flush=True)
                browser.close(); browser = None
        finally:
            if browser:
                try: browser.close()
                except Exception: pass
            server.terminate()
            try: server.wait(timeout=10)
            except subprocess.TimeoutExpired: server.kill(); server.wait()
            server_log.close()
            shutil.copyfile(home / 'server.log', evidence / 'migration-server.log')


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.get('children', []))


def wait_artwork(frame):
    frame.locator('#artboard, .studio-stage').evaluate("""async root=>{
      await document.fonts.ready;
      await Promise.allSettled([...root.querySelectorAll('img')].map(image=>image.decode()));
      const paths=[...new Set([...root.querySelectorAll('svg image')].map(image=>image.getAttribute('href')||image.getAttribute('xlink:href')).filter(Boolean))];
      await Promise.allSettled(paths.map(path=>new Promise(resolve=>{const image=new Image();image.onload=image.onerror=resolve;image.src=path;})));
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    }""")


if __name__ == '__main__':
    main()
