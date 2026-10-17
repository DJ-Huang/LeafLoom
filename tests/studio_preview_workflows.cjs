// Explicit editor/preview switching against the real browser and service.
// Invoked after the blank, FORMA and Motion Lab workflows have built their projects.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const flatten = nodes => nodes.flatMap(node => [node, ...flatten(node.children || [])]);

module.exports = async function previewWorkflows({page, request, info, checks}) {
  const canvas = () => page.frameLocator('.dw-runtime');
  const node = id => canvas().locator('[data-studio-node="' + id + '"]').first();
  const edit = () => page.getByTestId('studio-mode-edit');
  const preview = () => page.getByTestId('studio-mode-preview');
  const inspector = () => page.locator('.dw-inspector');
  const evidence = path.resolve(__dirname, '../.cache/studio-qa');
  fs.mkdirSync(evidence, {recursive: true});
  const enter = async () => {
    await preview().click();
    await page.locator('.design-workbench.is-preview').waitFor();
    await page.locator('.dw-sidebar').waitFor({state: 'hidden'});
    await inspector().waitFor({state: 'hidden'});
    assert.equal(await preview().getAttribute('aria-pressed'), 'true');
  };
  const leave = async () => {
    await edit().click();
    await page.locator('.design-workbench:not(.is-preview)').waitFor();
    await inspector().waitFor();
    assert.equal(await edit().getAttribute('aria-pressed'), 'true');
  };
  const home = async () => {
    if (await page.locator('.design-workbench.is-preview').count()) await leave();
    if (await page.locator('.design-workbench').count()) await page.locator('.dw-toolbar').getByRole('button', {name: '返回项目', exact: true}).click();
  };
  const open = async name => {
    await home();
    await page.locator('.design-project-title').getByText(name, {exact: true}).click();
    await canvas().locator('.studio-stage').waitFor();
  };
  const saved = () => page.locator('.dw-save-status').filter({hasText: '已保存'}).waitFor();
  const waitFor = async (read, predicate, label) => {
    let value;
    const end = Date.now() + 10000;
    do {
      value = await read();
      if (predicate(value)) return value;
      await page.waitForTimeout(50);
    } while (Date.now() < end);
    assert.fail(label + ': ' + JSON.stringify(value));
  };

  // An entirely empty project is a valid preview, without insertion/edit affordances.
  await home();
  await page.locator('.design-home-heading').getByRole('button', {name: '新建设计项目', exact: true}).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('项目文件夹名称（英文或中文目录名）', {exact: true}).fill('PreviewEmpty');
  await dialog.getByLabel('项目显示名称', {exact: true}).fill('Preview Empty');
  await dialog.getByRole('button', {name: '创建并打开设计工作台', exact: true}).click();
  await canvas().locator('.studio-stage').waitFor();
  await enter();
  assert.equal(await canvas().locator('[data-studio-node]').count(), 0);
  assert.equal(await page.locator('.dw-toolbar').getByRole('button', {name: '插入', exact: true}).isVisible(), false);
  await page.screenshot({path: path.join(evidence, 'preview-empty.png'), fullPage: true});
  await leave();
  checks.push('explicit-preview-empty-project-and-hidden-editor-controls');

  // Clicking preview directly blurs the field and must wait for its queued save.
  await open('My FORMA Studio');
  const forma = await request('design/document?directory=FormaWorkflow');
  const title = forma.document.pages.flatMap(item => flatten(item.nodes)).find(item => item.props?.text === 'Designed by our studio');
  assert.ok(title);
  await canvas().locator('[data-studio-select-id="' + title.id + '"]').click();
  await inspector().locator(':scope > .dw-tabs').getByRole('button', {name: '设计', exact: true}).click();
  await page.getByLabel('缩放比例', {exact: true}).selectOption('50');
  await waitFor(() => canvas().locator('.studio-stage').evaluate(el => el.style.transform), value => value.includes('scale(0.5)'), 'Explicit editor zoom');
  const camera = await canvas().locator('.studio-stage').evaluate(el => el.style.transform);
  const heading = await page.locator('.dw-canvas-heading > span').innerText();
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let intercepted = false;
  const delayed = async route => { intercepted = true; await gate; await route.continue(); };
  await page.route('**/api/design/operations', delayed);
  const field = inspector().getByLabel('文字内容', {exact: true});
  await field.fill('Latest text in explicit preview');
  await preview().click();
  try {
    await waitFor(() => Promise.resolve(intercepted), Boolean, 'Save request intercepted');
    await page.locator('.dw-preview-status').filter({hasText: '正在保存'}).waitFor();
    assert.equal(await page.locator('.design-workbench.is-preview').count(), 0);
  } finally { release(); }
  await page.locator('.design-workbench.is-preview').waitFor();
  await node(title.id).filter({hasText: 'Latest text in explicit preview'}).waitFor();
  await page.unroute('**/api/design/operations', delayed);
  const before = await request('design/document?directory=FormaWorkflow');
  for (const key of ['Delete', 'Backspace', 'Control+d', 'Control+z', 'Control+Shift+z']) {
    await preview().press(key);
    await canvas().locator('.studio-viewport').press(key);
  }
  await page.waitForTimeout(250);
  assert.equal((await request('design/document?directory=FormaWorkflow')).revision, before.revision, 'Editor shortcuts do not mutate preview');
  const targetPage = forma.document.pages.find(item => item.id !== forma.document.pages[0].id);
  await page.getByTestId('studio-preview-page').selectOption(targetPage.id);
  await waitFor(() => page.getByTestId('studio-preview-page').inputValue(), value => value === targetPage.id, 'Preview picker navigates without changing editor return page');
  await page.getByTestId('studio-preview-replay').click();
  await page.screenshot({path: path.join(evidence, 'preview-forma.png'), fullPage: true});
  await leave();
  await node(title.id).filter({hasText: 'Latest text in explicit preview'}).waitFor();
  await waitFor(() => node(title.id).getAttribute('class'), value => value.includes('studio-selected'), 'Returning restores selected layer');
  assert.equal(await canvas().locator('.studio-stage').evaluate(el => el.style.transform), camera);
  assert.equal(await page.locator('.dw-canvas-heading > span').innerText(), heading);
  checks.push('explicit-preview-waits-for-latest-save-and-restores-page-selection-camera');
  checks.push('explicit-preview-page-picker-replay-and-mutation-shortcut-guard');

  // Failed saves keep recoverable edits in the editor instead of showing stale output.
  await page.route('**/api/design/operations', route => route.abort('failed'));
  await field.fill('Retained text after failed preview save');
  await preview().click();
  await page.locator('.dw-conflict').waitFor();
  await page.locator('.dw-preview-status').filter({hasText: '预览未启动'}).waitFor();
  assert.equal(await page.locator('.design-workbench.is-preview').count(), 0);
  assert.equal(await page.evaluate(() => Object.keys(localStorage).some(key => key.startsWith('leafloom-design-queue:') && JSON.parse(localStorage.getItem(key)).length > 0)), true);
  await page.unroute('**/api/design/operations');
  await page.locator('.dw-conflict').getByRole('button', {name: '重试原操作', exact: true}).click();
  await saved();
  await enter();
  await node(title.id).filter({hasText: 'Retained text after failed preview save'}).waitFor();
  await leave();
  checks.push('explicit-preview-save-failure-preserves-queue-and-retry-shows-latest-content');

  // Native inline canvas editing must flush before changing runtime mode.
  await open('Browser Studio');
  await canvas().locator('[data-studio-select-id="fixture-title"]').dblclick();
  const inline = canvas().locator('[contenteditable]');
  await inline.fill('Inline canvas changes reach preview');
  await enter();
  await node('fixture-title').filter({hasText: 'Inline canvas changes reach preview'}).waitFor();
  assert.equal((await request('design/document?directory=Studio')).document.pages.flatMap(item => flatten(item.nodes)).find(item => item.id === 'fixture-title').props.text, 'Inline canvas changes reach preview');
  await canvas().locator('.studio-viewport').press('Escape');
  await page.locator('.design-workbench:not(.is-preview)').waitFor();
  await inspector().waitFor();
  await waitFor(() => node('fixture-title').getAttribute('class'), value => value.includes('studio-selected'), 'Iframe Escape returns to the selected editor layer');
  checks.push('explicit-preview-flushes-inline-canvas-text-and-iframe-escape-returns-to-editor');

  // Existing Motion Lab checks exercise actual preset frames and scripted motion.
  // Repeated mode switches additionally verify they clean up inside the editor iframe.
  await open('My Motion Lab');
  const revision = (await request('design/document?directory=MotionWorkflow')).revision;
  for (let cycle = 0; cycle < 4; cycle++) {
    await enter();
    await waitFor(() => canvas().locator('.studio-stage').evaluate(el => el.getAnimations({subtree: true}).length), value => value > 0, 'Motion preview starts actual animations');
    await node('motion-orbit').click();
    await node('motion-open-guide').click();
    await node('motion-guide-back').waitFor();
    await leave();
    await node('motion-orbit-status').filter({hasText: 'At rest · tap to orbit'}).waitFor();
    await waitFor(() => canvas().locator('.studio-stage').evaluate(el => el.getAnimations({subtree: true}).length), value => value === 0, 'Leaving preview releases animations');
    assert.equal(await page.locator('.dw-runtime').count(), 1);
    assert.equal(await canvas().locator('.studio-overlay,.studio-runtime-error').count(), 0);
  }
  assert.equal((await request('design/document?directory=MotionWorkflow')).revision, revision);
  checks.push('explicit-preview-repeated-motion-navigation-and-clean-return-without-document-mutations');
};
