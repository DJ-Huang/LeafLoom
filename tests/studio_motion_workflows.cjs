// Real picker/editor workflow, followed by the exact downloaded portable bundle.
// Runs through studio_workbench_browser.cjs and its isolated full-stack fixture.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');

const resourceKeys = ['animations', 'listeners', 'timers', 'frames', 'objectUrls', 'previewGroups', 'ownedResources'];
const flatten = nodes => nodes.flatMap(node => [node, ...flatten(node.children || [])]);
const allNodes = document => document.pages.flatMap(page => flatten(page.nodes));
const pickResources = stats => Object.fromEntries(resourceKeys.map(key => [key, stats[key]]));

async function until(page, read, predicate, message) {
  const deadline = Date.now() + 10000;
  let value;
  do {
    value = await read();
    if (predicate(value)) return value;
    await page.waitForTimeout(50);
  } while (Date.now() < deadline);
  assert.fail(message + ': ' + JSON.stringify(value));
}

// Read the real visual effect, which lives on the content rather than its
// editable wrapper. Do not infer motion from saved JSON alone.
async function effects(node) {
  return node.evaluate(el => {
    const visual = el.querySelector(':scope > .studio-content') || el;
    return visual.getAnimations().map(animation => ({
      state: animation.playState,
      time: animation.currentTime,
      timing: animation.effect.getTiming(),
      frames: animation.effect.getKeyframes(),
    }));
  });
}

async function seekEffect(node, progress) {
  return node.evaluate((el, progress) => {
    const visual = el.querySelector(':scope > .studio-content') || el;
    const animation = visual.getAnimations()[0];
    if (!animation) throw new Error('The UI trigger did not create an animation');
    const timing = animation.effect.getTiming();
    animation.pause();
    animation.currentTime = timing.delay + Number(timing.duration) * progress;
    const style = getComputedStyle(visual);
    return {translate: style.translate, scale: style.scale, opacity: style.opacity};
  }, progress);
}

// Browser-native PNG decoding keeps image comparison independent of optional
// Pillow/ffmpeg packages. Both images come from the same fixed screenshot clip.
async function compareFrames(page, before, after) {
  return page.evaluate(async ([before, after]) => {
    const decode = async source => {
      const image = new Image();
      image.src = 'data:image/png;base64,' + source;
      await image.decode();
      const canvas = document.createElement('canvas');
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const context = canvas.getContext('2d');
      context.drawImage(image, 0, 0);
      return {width: canvas.width, height: canvas.height, pixels: context.getImageData(0, 0, canvas.width, canvas.height).data};
    };
    const a = await decode(before), b = await decode(after);
    if (a.width !== b.width || a.height !== b.height) throw new Error('Screenshot dimensions changed');
    let changed = 0;
    for (let offset = 0; offset < a.pixels.length; offset += 4) {
      if ([0, 1, 2].some(channel => Math.abs(a.pixels[offset + channel] - b.pixels[offset + channel]) > 12)) changed++;
    }
    return {width: a.width, height: a.height, changedPixels: changed, changedFraction: changed / (a.width * a.height)};
  }, [before.toString('base64'), after.toString('base64')]);
}

async function captureBounce({page, node, evidence, prefix}) {
  await node.scrollIntoViewIfNeeded();
  const bounds = await node.boundingBox();
  assert.ok(bounds && bounds.width > 0 && bounds.height > 0);
  const viewport = page.viewportSize();
  const x = Math.max(0, Math.floor(bounds.x - 24)), y = Math.max(0, Math.floor(bounds.y - 24));
  const clip = {
    x, y,
    width: Math.min(viewport.width - x, Math.ceil(bounds.width + 48)),
    height: Math.min(viewport.height - y, Math.ceil(bounds.height + 48)),
  };
  const before = await page.screenshot({path: path.join(evidence, prefix + '-before.png'), clip});
  await node.click();
  await until(page, () => effects(node), values => values.length === 1, 'Click should start one bounce effect');
  const frames = [], styles = [];
  for (const [index, progress] of [0, .25, .5, .75, 1].entries()) {
    styles.push(await seekEffect(node, progress));
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    frames.push(await page.screenshot({path: path.join(evidence, prefix + '-frame-' + index + '.png'), clip}));
  }
  assert.notEqual(styles[2].translate, styles[0].translate, 'The midpoint must visibly move the card');
  const comparison = await compareFrames(page, before, frames[2]);
  assert.ok(comparison.changedPixels > 80, 'The clicked bounce must change rendered pixels');
  // A self-contained replay of sampled screenshots is evidence, not a claimed
  // real-time recording. Keep the original PNG frames alongside this viewer.
  fs.writeFileSync(path.join(evidence, prefix + '-sampled-frames.html'), '<!doctype html><meta charset="utf-8"><title>Motion: sampled bounce frames</title><style>body{font:16px system-ui;background:#eef0f4;padding:24px}img{display:block;border:1px solid #ccc}</style><h1>Sampled frames from a real click-triggered bounce</h1><p>Five animation phases, paused and captured from the browser. This is a frame replay, not a real-time recording.</p><img alt="Click-triggered bounce phases"><script>const frames=' + JSON.stringify(frames.map(frame => 'data:image/png;base64,' + frame.toString('base64'))) + ';let i=0;const image=document.querySelector("img");image.src=frames[0];setInterval(()=>{i=(i+1)%frames.length;image.src=frames[i]},200);</script>');
  return {comparison, styles};
}

async function scriptInteractions({page, node, evidence, prefix, turn = 150}) {
  const orbit = node('motion-orbit'), ring = node('motion-orbit-ring');
  const tilt = node('motion-tilt'), tiltObject = node('motion-tilt-object');
  const pressed = target => target.evaluate(el => (el.querySelector(':scope > .studio-content') || el).getAttribute('aria-pressed'));
  const transform = target => target.evaluate(el => (el.querySelector(':scope > .studio-content') || el).style.transform);
  await until(page, () => pressed(orbit), value => value === 'false', 'Orbit begins in its accessible resting state');
  await orbit.scrollIntoViewIfNeeded();
  const bounds = await orbit.boundingBox();
  const clip = {x: Math.max(0, Math.floor(bounds.x)), y: Math.max(0, Math.floor(bounds.y)), width: Math.floor(bounds.width), height: Math.floor(bounds.height)};
  const before = await page.screenshot({path: path.join(evidence, prefix + '-before.png'), clip});
  await orbit.click();
  await until(page, () => pressed(orbit), value => value === 'true', 'Click starts the scripted spring');
  await until(page, () => transform(ring), value => value === 'rotate(' + turn + 'deg)', 'Spring reaches its configured endpoint');
  assert.equal(await node('motion-orbit-status').innerText(), 'In orbit · tap to return');
  const after = await page.screenshot({path: path.join(evidence, prefix + '-after.png'), clip});
  const comparison = await compareFrames(page, before, after);
  assert.ok(comparison.changedPixels > 80, 'A real spring click changes the rendered artwork and status');
  await orbit.press('Enter');
  await until(page, () => pressed(orbit), value => value === 'false', 'Enter activates the same native control');
  await until(page, () => transform(ring), value => value === 'rotate(0deg)', 'Keyboard activation returns the spring to rest');
  assert.equal(await node('motion-orbit-status').innerText(), 'At rest · tap to orbit');

  await tilt.scrollIntoViewIfNeeded();
  const tiltBounds = await tilt.boundingBox();
  await page.mouse.move(tiltBounds.x + tiltBounds.width * .8, tiltBounds.y + tiltBounds.height * .3);
  await until(page, () => transform(tiltObject), value => /rotate[XY]\([^0][^)]*deg\)/.test(value), 'Pointer movement tilts the artwork');
  await tilt.click();
  await until(page, () => pressed(tilt), value => value === 'true', 'Tilt has a click alternative to pointer movement');
  assert.equal(await node('motion-tilt-status').innerText(), 'Tilt selected · tap to reset');
  await tilt.press('Enter');
  await until(page, () => pressed(tilt), value => value === 'false', 'Keyboard activation resets tilt');
  await page.mouse.move(2, 2);
  return {comparison, turn};
}

module.exports = async function motionWorkflows({page, request, info, checks}) {
  const root = path.resolve(__dirname, '..');
  const evidence = path.join(root, '.cache/studio-qa');
  fs.mkdirSync(evidence, {recursive: true});
  const report = {workflow: 'motion', frames: {}, resources: {}, export: {}};
  const read = () => request('design/document?directory=MotionWorkflow');
  const inspector = () => page.locator('.dw-inspector');
  const canvas = () => page.frameLocator('.dw-runtime');
  const node = id => canvas().locator('[data-studio-node="' + id + '"]').first();
  const toolbar = () => page.locator('.dw-toolbar');
  const mutate = async action => {
    const pending = page.waitForResponse(response => new URL(response.url()).pathname === '/api/design/operations' && response.request().method() === 'POST');
    pending.catch(() => {});
    await action();
    const response = await pending;
    assert.ok(response.ok(), await response.text());
    await page.locator('.dw-save-status').filter({hasText: '已保存'}).waitFor();
  };
  const field = async (label, value) => {
    const input = inspector().getByLabel(label, {exact: true});
    if (await input.inputValue() === String(value)) return;
    await mutate(async () => { await input.fill(String(value)); await input.blur(); });
  };
  const tab = label => inspector().locator(':scope > .dw-tabs').getByRole('button', {name: label, exact: true}).click();
  const selectNode = async id => {
    // The bounce is circular and scripted cards have painted child layers.
    // Select their exact native layer row rather than guessing a hit point.
    const owner = saved.document.pages.find(item => flatten(item.nodes).some(child => child.id === id));
    const rows = flatten(owner.nodes), index = rows.findIndex(item => item.id === id);
    await page.locator('.dw-sidebar > .dw-tabs').getByRole('button', {name: '图层', exact: true}).click();
    await page.locator('.dw-sidebar .dw-virtual').evaluate((el, top) => {
      el.scrollTop = top;
      el.dispatchEvent(new Event('scroll', {bubbles: true}));
    }, index * 32);
    await page.locator('.dw-sidebar .dw-virtual').getByTitle(rows[index].name, {exact: true}).click();
    await until(page, () => node(id).getAttribute('class'), value => value.includes('studio-selected'), 'Layer selection should reach ' + id);
  };
  const stop = async () => {
    await toolbar().getByRole('button', {name: '编辑', exact: true}).click();
    await until(page, () => canvas().locator('.studio-stage').evaluate(el => el.getAnimations({subtree: true}).length), count => count === 0, 'Stopping preview releases active effects');
  };

  if (await page.getByRole('dialog').count()) await page.getByRole('dialog').getByRole('button', {name: '取消', exact: true}).click();
  if (await page.locator('.design-workbench').count()) await toolbar().getByRole('button', {name: '返回项目', exact: true}).click();
  await page.locator('.design-home-heading').getByRole('button', {name: '新建设计项目', exact: true}).click();
  const dialog = page.getByRole('dialog');
  await dialog.locator('[data-template-id="motion"]').click();
  assert.equal(await dialog.locator('input[name="design-template"][value="motion"]').isChecked(), true);
  await dialog.locator('[data-template-id="motion"] .design-template-motion').waitFor();
  assert.equal(await dialog.locator('[data-template-id="motion"] .design-motion-orbit').isVisible(), true);
  await dialog.getByLabel('项目文件夹名称（英文或中文目录名）', {exact: true}).fill('MotionWorkflow');
  await dialog.getByLabel('项目显示名称', {exact: true}).fill('My Motion Lab');
  await page.screenshot({path: path.join(evidence, 'motion-template-picker.png'), fullPage: true});
  const creation = page.waitForResponse(response => new URL(response.url()).pathname === '/api/design/projects' && response.request().method() === 'POST');
  await dialog.getByRole('button', {name: '创建并打开设计工作台', exact: true}).click();
  const created = await creation;
  assert.ok(created.ok(), await created.text());
  assert.equal(created.request().postDataJSON().template_id, 'motion');
  await toolbar().locator('strong').filter({hasText: 'My Motion Lab'}).waitFor();
  let saved = await read();
  const original = saved.document;
  assert.deepEqual(original.pages.map(item => item.id).sort(), ['motion-guide', 'motion-home', 'motion-mobile']);
  assert.equal(await page.locator('.dw-page-list > button').count(), 3);
  const find = id => allNodes(saved.document).find(item => item.id === id);
  assert.deepEqual([1, 2, 3].map(index => find('motion-stagger-' + index).animation.delay), [0, 120, 240]);
  assert.equal(find('motion-hover').animation.trigger, 'hover');
  assert.equal(find('motion-bounce').animation.trigger, 'click');
  await node('motion-bounce').waitFor();
  assert.equal(await canvas().locator('.studio-stage').evaluate(el => el.getAnimations({subtree: true}).length), 0);
  checks.push('motion-real-picker-preview-three-editable-pages');

  await selectNode('motion-bounce');
  await tab('动画');
  assert.equal(await inspector().getByLabel('效果', {exact: true}).inputValue(), 'bounce');
  await field('时长（毫秒）', 960);
  await field('延迟（毫秒）', 30);
  await field('循环次数', 2);
  await field('缓动', 'linear');
  saved = await read();
  assert.deepEqual(Object.fromEntries(['preset', 'trigger', 'duration', 'delay', 'iterations', 'easing'].map(key => [key, find('motion-bounce').animation[key]])), {
    preset: 'bounce', trigger: 'click', duration: 960, delay: 30, iterations: 2, easing: 'linear',
  });

  await selectNode('motion-tilt');
  await tab('脚本');
  const scripted = find('motion-tilt');
  const parameter = Object.entries(scripted.script.parameters).find(([, descriptor]) => descriptor.type === 'number');
  assert.ok(parameter, 'The tilt demo exposes a numeric script control');
  const [parameterKey, descriptor] = parameter;
  const parameterValue = Number(scripted.script.props?.[parameterKey] ?? descriptor.default) + 1;
  await field(descriptor.label || parameterKey, parameterValue);
  saved = await read();
  assert.equal(find('motion-tilt').script.props[parameterKey], parameterValue);
  report.scriptParameter = {nodeId: 'motion-tilt', key: parameterKey, value: parameterValue};
  await toolbar().getByRole('button', {name: '返回项目', exact: true}).click();
  await page.locator('.design-project-title').getByText('My Motion Lab', {exact: true}).click();
  await node('motion-bounce').waitFor();
  saved = await read();
  assert.equal(find('motion-bounce').animation.duration, 960);
  assert.equal(find('motion-tilt').script.props[parameterKey], parameterValue);
  await selectNode('motion-bounce');
  await tab('动画');
  assert.equal(await inspector().getByLabel('时长（毫秒）', {exact: true}).inputValue(), '960');
  await page.screenshot({path: path.join(evidence, 'motion-edited-reopened.png'), fullPage: true});
  checks.push('motion-animation-and-script-props-edited-saved-reopened');

  await toolbar().getByRole('button', {name: '预览', exact: true}).click();
  await until(page, () => effects(node('motion-stagger-1')), values => values.length === 1, 'Appear animation should start in preview');
  for (const index of [1, 2, 3]) {
    const [effect] = await effects(node('motion-stagger-' + index));
    assert.equal(effect.timing.delay, [0, 120, 240][index - 1]);
  }
  await node('motion-hover').hover();
  await until(page, () => effects(node('motion-hover')), values => values.length === 1, 'Hover should start scale animation');
  assert.ok((await effects(node('motion-hover')))[0].frames.some(frame => frame.scale && frame.scale !== '1'));
  report.frames.editorBounce = await captureBounce({page, node: node('motion-bounce'), evidence, prefix: 'motion-editor-bounce'});
  checks.push('motion-preview-stagger-hover-click-and-rendered-frame-comparison');
  report.frames.editorScript = await scriptInteractions({page, node, evidence, prefix: 'motion-editor-orbit'});
  await node('motion-open-guide').click();
  await node('motion-guide-back').waitFor();
  await node('motion-guide-back').click();
  await node('motion-orbit').waitFor();
  checks.push('motion-preview-script-pointer-click-keyboard-and-page-navigation');

  // Remaining script and export checks below deliberately use the bundle saved
  // by this workflow, so a stale packaged sample cannot mask editor save bugs.
  await stop();
  assert.equal(await node('motion-orbit-status').innerText(), 'At rest · tap to orbit');
  assert.equal(await node('motion-tilt-status').innerText(), 'Move your pointer · or tap');
  const exportResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/design/export' && response.request().method() === 'POST');
  const downloadEvent = page.waitForEvent('download');
  await toolbar().getByRole('button', {name: '导出', exact: true}).click();
  const download = await downloadEvent;
  assert.equal(await download.failure(), null);
  const bundle = path.join(evidence, 'motion-workflow.zip');
  await download.saveAs(bundle);
  const exported = await (await exportResponse).json();
  report.export.revision = exported.revision;
  fs.writeFileSync(path.join(evidence, 'motion-workflow-document.json'), JSON.stringify(saved.document, null, 2));

  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'leafloom-motion-export-'));
  const python = process.env.LEAFLOOM_PYTHON || path.join(root, '.venv/bin/python');
  execFileSync(python, ['-m', 'zipfile', '-e', bundle, directory]);
  for (const name of ['index.html', 'runtime.js', 'runtime.css', 'document.js']) assert.ok(fs.existsSync(path.join(directory, name)), 'Portable bundle contains ' + name);
  const portableDocument = JSON.parse(fs.readFileSync(path.join(directory, 'document.js'), 'utf8').replace(/^window\.STUDIO_DOCUMENT=/, '').trim().replace(/;$/, ''));
  assert.deepEqual(portableDocument.pages, saved.document.pages);
  const mountedListeners = pageId => flatten(portableDocument.pages.find(item => item.id === pageId).nodes).reduce((count, item) => count
    + (item.props?.navigateTo ? 1 : 0)
    + (item.animation ? 1 + (item.animation.trigger === 'hover' ? 3 : item.animation.trigger === 'click' ? 1 : 0) : 0)
    + (item.script?.source.match(/\bctx\.on\s*\(/g)?.length || 0), 0);
  const portableOrigin = 'http://motion-export.test';
  const serveBundle = async target => {
    const requested = [];
    await target.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.protocol === 'blob:' || url.protocol === 'data:') return route.continue();
      assert.equal(url.origin, portableOrigin, 'Portable demo must not need a remote service');
      const file = path.resolve(directory, '.' + decodeURIComponent(url.pathname));
      assert.ok(file.startsWith(directory + path.sep), 'Export request stays inside its bundle');
      requested.push(url.pathname);
      if (!fs.existsSync(file)) return route.fulfill({status: 404, body: 'Not in bundle'});
      const contentType = ({'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png'})[path.extname(file)] || 'application/octet-stream';
      await route.fulfill({body: fs.readFileSync(file), contentType});
    });
    await target.goto(portableOrigin + '/index.html');
    await target.waitForFunction(() => !!window.LeafLoomStudioInstance);
    return requested;
  };
  const playback = await page.context().newPage();
  const playbackErrors = [];
  playback.on('pageerror', error => playbackErrors.push(error.message));
  const portableNode = id => playback.locator('[data-studio-node="' + id + '"]').first();
  try {
    report.export.requestedFiles = await serveBundle(playback);
    await portableNode('motion-bounce').waitFor();
    await playback.waitForFunction(expected => window.LeafLoomStudioInstance.debugStats.objectUrls >= 2 && window.LeafLoomStudioInstance.debugStats.listeners >= expected, mountedListeners('motion-home'));
    report.resources.home = await playback.evaluate(() => window.LeafLoomStudioInstance.debugStats);
    report.frames.exportBounce = await captureBounce({page: playback, node: portableNode('motion-bounce'), evidence, prefix: 'motion-export-bounce'});
    assert.equal((await effects(portableNode('motion-bounce')))[0].timing.duration, 960);
    checks.push('motion-exact-downloaded-html-replays-edited-animation-offline');
    report.frames.exportScript = await scriptInteractions({page: playback, node: portableNode, evidence, prefix: 'motion-export-orbit'});
    assert.equal(await playback.locator('.studio-runtime-error').count(), 0);
    checks.push('motion-portable-script-click-keyboard-and-rendered-frame-comparison');

    // Repeated real inputs must replace the preset instead of accumulating
    // animation resources for the duration of a long preview session.
    for (let index = 0; index < 8; index++) {
      await portableNode('motion-bounce').click();
      await playback.mouse.move(2, 2);
      await portableNode('motion-hover').hover();
      assert.equal((await effects(portableNode('motion-bounce'))).length, 1);
      assert.equal((await effects(portableNode('motion-hover'))).length, 1);
    }
    report.resources.replayed = await playback.evaluate(() => window.LeafLoomStudioInstance.debugStats);
    assert.equal(report.resources.replayed.animations, report.resources.home.animations + 2);

    await playback.emulateMedia({reducedMotion: 'reduce'});
    await until(playback, () => playback.evaluate(() => window.LeafLoomStudioInstance.debugStats), stats => stats.animations === 0 && stats.frames === 0, 'Live reduced motion cancels presets and script frame callbacks');
    await portableNode('motion-orbit').click();
    assert.equal(await portableNode('motion-orbit-ring').evaluate(el => el.style.transform), 'rotate(150deg)');
    assert.equal(await portableNode('motion-orbit-status').innerText(), 'In orbit · tap to return');
    await portableNode('motion-bounce').click();
    await portableNode('motion-hover').hover();
    assert.equal(await playback.locator('.studio-stage').evaluate(el => el.getAnimations({subtree: true}).length), 0);
    await playback.screenshot({path: path.join(evidence, 'motion-reduced-motion.png'), fullPage: true});
    report.resources.reduced = await playback.evaluate(() => window.LeafLoomStudioInstance.debugStats);
    await playback.emulateMedia({reducedMotion: 'no-preference'});
    await until(playback, () => playback.evaluate(() => window.LeafLoomStudioInstance.debugStats.animations), count => count === report.resources.home.animations, 'Restoring motion restarts only appearance presets');
    checks.push('motion-replay-bounds-resources-and-live-reduced-motion-preserves-actions');

    await portableNode('motion-open-guide').click();
    await portableNode('motion-guide-back').waitFor();
    report.resources.guide = await playback.evaluate(() => window.LeafLoomStudioInstance.debugStats);
    for (const key of ['animations', 'timers', 'frames', 'objectUrls']) assert.equal(report.resources.guide[key], 0, 'Navigating away releases ' + key);
    await playback.screenshot({path: path.join(evidence, 'motion-export-guide.png'), fullPage: true});
    await portableNode('motion-guide-back').click();
    await portableNode('motion-orbit').waitFor();
    await playback.waitForFunction(() => window.LeafLoomStudioInstance.debugStats.objectUrls >= 2);
    await until(playback, () => playback.evaluate(() => window.LeafLoomStudioInstance.debugStats), stats => stats.listeners === report.resources.home.listeners && stats.frames === 0, 'Remount resource count returns to baseline');
    report.resources.returnedHome = await playback.evaluate(() => window.LeafLoomStudioInstance.debugStats);
    assert.deepEqual(pickResources(report.resources.returnedHome), pickResources(report.resources.home));
    await playback.evaluate(() => window.LeafLoomStudioInstance.dispose());
    report.resources.disposed = await playback.evaluate(() => window.LeafLoomStudioInstance.debugStats);
    for (const key of resourceKeys) assert.equal(report.resources.disposed[key], 0, 'Disposing the export releases ' + key);
    assert.equal(await playback.locator('#studio-root').innerHTML(), '');
    assert.deepEqual(playbackErrors, []);
    checks.push('motion-export-page-navigation-remount-and-dispose-resource-cleanup');
  } finally {
    await playback.close();
    fs.writeFileSync(path.join(evidence, 'motion-workflow-report.json'), JSON.stringify(report, null, 2));
  }

  // A fresh phone-sized, touch-capable context proves reduced-motion is honored
  // at first mount as well as during live preference changes above.
  const touchContext = await page.context().browser().newContext({viewport: {width: 390, height: 844}, hasTouch: true, isMobile: true, reducedMotion: 'reduce'});
  const touch = await touchContext.newPage();
  const touchErrors = [];
  touch.on('pageerror', error => touchErrors.push(error.message));
  const touchNode = id => touch.locator('[data-studio-node="' + id + '"]').first();
  try {
    await serveBundle(touch);
    await touchNode('motion-open-mobile').tap();
    await touchNode('motion-mobile-orbit').waitFor();
    await touch.waitForFunction(expected => window.LeafLoomStudioInstance.debugStats.objectUrls >= 2 && window.LeafLoomStudioInstance.debugStats.listeners >= expected, mountedListeners('motion-mobile'));
    assert.equal(await touch.locator('.studio-stage').evaluate(el => el.getAnimations({subtree: true}).length), 0);
    assert.equal(await touch.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), true);
    assert.equal(await touch.evaluate(() => navigator.maxTouchPoints > 0), true);
    await touchNode('motion-mobile-orbit').tap();
    assert.equal(await touchNode('motion-mobile-orbit').getAttribute('aria-pressed'), 'true');
    assert.equal(await touchNode('motion-mobile-orbit-status').innerText(), 'In orbit · tap to return');
    assert.equal(await touchNode('motion-mobile-orbit-ring').evaluate(el => el.style.transform), 'rotate(150deg)');
    const tiltOriginal = await touchNode('motion-mobile-tilt-object').evaluate(el => el.style.transform);
    await touchNode('motion-mobile-tilt').tap();
    assert.equal(await touchNode('motion-mobile-tilt').getAttribute('aria-pressed'), 'true');
    assert.equal(await touchNode('motion-mobile-tilt-object').evaluate(el => el.style.transform), tiltOriginal);
    report.resources.touchReduced = await touch.evaluate(() => window.LeafLoomStudioInstance.debugStats);
    assert.equal(report.resources.touchReduced.animations, 0);
    assert.equal(report.resources.touchReduced.frames, 0);
    for (const id of ['motion-mobile-orbit', 'motion-mobile-tilt']) assert.ok(await touchNode(id).evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'Narrow interactive card does not clip horizontal content');
    await touch.screenshot({path: path.join(evidence, 'motion-narrow-touch-reduced.png'), fullPage: true});

    await touch.emulateMedia({reducedMotion: 'no-preference'});
    await touchNode('motion-mobile-hover').tap();
    await until(touch, () => effects(touchNode('motion-mobile-hover')), values => values.length === 1, 'Hover example also responds to touch');
    await touchNode('motion-mobile-bounce').tap();
    await until(touch, () => effects(touchNode('motion-mobile-bounce')), values => values.length === 1, 'Click example responds to touch');
    await touchNode('motion-mobile-orbit').tap();
    await until(touch, () => touchNode('motion-mobile-orbit-ring').evaluate(el => el.style.transform), value => value === 'rotate(0deg)', 'Touch spring settles after motion is re-enabled');
    await touch.screenshot({path: path.join(evidence, 'motion-narrow-touch.png'), fullPage: true});
    await touchNode('motion-mobile-open-mobile').tap();
    await touchNode('motion-open-mobile').waitFor();
    assert.equal(await touch.locator('.studio-runtime-error').count(), 0);
    await touch.evaluate(() => window.LeafLoomStudioInstance.dispose());
    report.resources.touchDisposed = await touch.evaluate(() => window.LeafLoomStudioInstance.debugStats);
    for (const key of resourceKeys) assert.equal(report.resources.touchDisposed[key], 0);
    assert.deepEqual(touchErrors, []);
    checks.push('motion-narrow-touch-fallbacks-initial-reduced-motion-and-cleanup');
  } finally {
    await touchContext.close();
    fs.writeFileSync(path.join(evidence, 'motion-workflow-report.json'), JSON.stringify(report, null, 2));
    fs.rmSync(directory, {recursive: true, force: true});
  }
};
