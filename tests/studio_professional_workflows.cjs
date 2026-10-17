// Professional editor acceptance: real UI edits, keyboard operation and rendered exports.
// Called by studio_workbench_browser.cjs against its disposable vault, never user data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');

module.exports = async function professionalWorkflows({page, request, info, checks}) {
  const root = path.resolve(__dirname, '..');
  const evidence = path.join(root, '.cache/studio-qa');
  const python = process.env.LEAFLOOM_PYTHON || path.join(root, '.venv/bin/python');
  const directory = 'ProfessionalWorkflow';
  const name = 'Editorial Showcase';
  const templateId = 'atelier';
  const report = {viewports: [], exports: []};
  fs.mkdirSync(evidence, {recursive: true});
  const saveReport = () => fs.writeFileSync(path.join(evidence, 'professional-report.json'), JSON.stringify(report, null, 2));
  const read = () => request('design/document?directory=' + directory);
  const flatten = nodes => nodes.flatMap(node => [node, ...flatten(node.children || [])]);
  const toolbar = () => page.locator('.dw-toolbar');
  const canvas = () => page.frameLocator('.dw-runtime');
  const dialog = () => page.getByRole('dialog');
  const polishedScreenshot = async filename => {
    await page.locator('.toast').waitFor({state: 'hidden', timeout: 15000});
    await page.screenshot({path: path.join(evidence, filename), fullPage: true});
  };

  await toolbar().getByRole('button', {name: '返回项目', exact: true}).click();
  await page.locator('.design-home-heading').getByRole('button', {name: '新建设计项目', exact: true}).click();
  await dialog().locator('[data-template-id="' + templateId + '"]').click();
  assert.equal(await dialog().locator('input[name="design-template"][value="' + templateId + '"]').isChecked(), true);
  await dialog().getByLabel('项目文件夹名称（英文或中文目录名）', {exact: true}).fill(directory);
  await dialog().getByLabel('项目显示名称', {exact: true}).fill(name);
  const createdEvent = page.waitForResponse(response => new URL(response.url()).pathname === '/api/design/projects' && response.request().method() === 'POST');
  await dialog().getByRole('button', {name: '创建并打开设计工作台', exact: true}).click();
  const created = await createdEvent;
  assert.ok(created.ok(), await created.text());
  assert.equal(created.request().postDataJSON().template_id, templateId);
  await toolbar().locator('strong').filter({hasText: name}).waitFor();
  let saved = await read();
  assert.ok(saved.document.pages.length >= 2, 'The showcase must contain multiple genuine editable pages');
  const allNodes = saved.document.pages.flatMap(item => flatten(item.nodes));
  assert.ok(allNodes.filter(node => typeof node.props?.text === 'string' && node.props.text.trim()).length >= 12, 'The showcase must use editable text layers');
  assert.equal(allNodes.filter(node => node.type === 'html').length, 0, 'The showcase must not be a flattened HTML screenshot');
  const title = flatten(saved.document.pages[0].nodes).find(node => node.props?.bindingKey === 'atelier.hero');
  assert.ok(title, 'The opening page must have an editable display title');
  await canvas().locator('[data-studio-select-id="' + title.id + '"]').click();
  await page.locator('.dw-inspector>.dw-tabs').getByRole('button', {name: '数据', exact: true}).click();
  const text = page.locator('.dw-inspector').getByLabel('atelier.hero · 源数据', {exact: true});
  // Exercise the actual bound source; editing props alone would be projected out.
  const edited = 'A softer\nway to be.';
  assert.notEqual(edited, saved.document.bindings['atelier.hero'].value);
  const savedEvent = page.waitForResponse(response => new URL(response.url()).pathname === '/api/design/operations' && response.request().method() === 'POST');
  await text.fill(edited); await text.blur();
  const mutation = await savedEvent; assert.ok(mutation.ok(), await mutation.text());
  await page.locator('.dw-save-status').filter({hasText: '已保存'}).waitFor();
  await toolbar().getByRole('button', {name: '返回项目', exact: true}).click();
  await page.locator('.design-project-title').getByText(name, {exact: true}).click();
  await canvas().locator('[data-studio-select-id="' + title.id + '"]').filter({hasText: edited}).waitFor();
  saved = await read();
  assert.equal(saved.document.bindings['atelier.hero'].value, edited);
  checks.push('professional-template-real-editable-content-saved-and-reopened');

  await canvas().locator('[data-studio-select-id="' + title.id + '"]').click();
  await page.locator('.dw-inspector>.dw-tabs').getByRole('button', {name: '设计', exact: true}).click();
  const originalViewport = page.viewportSize();
  for (const viewport of [{width: 1560, height: 1050, label: 'desktop'}, {width: 1024, height: 820, label: 'narrow'}]) {
    await page.setViewportSize({width: viewport.width, height: viewport.height});
    await canvas().locator('.studio-stage').waitFor();
    const geometry = await page.evaluate(() => {
      const selectors = ['.design-workbench', '.dw-toolbar', '.dw-body', '.dw-canvas'];
      return {windowWidth: innerWidth, documentWidth: document.documentElement.scrollWidth, regions: selectors.map(selector => {
        const element = document.querySelector(selector), box = element.getBoundingClientRect();
        return {selector, left: box.left, right: box.right, width: box.width, height: box.height};
      })};
    });
    report.viewports.push({...viewport, ...geometry}); saveReport();
    await polishedScreenshot('professional-editor-' + viewport.label + '.png');
    assert.ok(geometry.documentWidth <= geometry.windowWidth + 1, JSON.stringify(geometry));
    for (const region of geometry.regions) {
      assert.ok(region.left >= -1 && region.right <= viewport.width + 1, JSON.stringify(region));
      assert.ok(region.width > 100 && region.height > 20, JSON.stringify(region));
    }
  }
  const panelToggle = page.getByTestId('studio-toggle-panels');
  const selectedIds = () => canvas().locator('.studio-selected').evaluateAll(elements => elements.map(element => element.getAttribute('data-studio-select-id') || element.getAttribute('data-studio-node')).filter(Boolean).sort());
  const selectedBefore = await selectedIds();
  assert.ok(selectedBefore.includes(title.id), 'The selected editable headline is present before changing panel visibility');
  const pageBefore = await page.locator('.dw-page-list>button.active').innerText();
  const canvasWidthBefore = await page.locator('.dw-canvas').evaluate(element => element.getBoundingClientRect().width);
  await panelToggle.click();
  await page.locator('.dw-sidebar').waitFor({state: 'hidden'});
  await page.locator('.dw-inspector').waitFor({state: 'hidden'});
  assert.equal(await panelToggle.getAttribute('aria-pressed'), 'true');
  assert.equal(await panelToggle.isVisible(), true);
  assert.equal(await page.getByTestId('studio-batch-publish').isVisible(), true);
  assert.equal(await page.getByTestId('studio-mode-preview').isVisible(), true);
  const canvasWidthFocused = await page.locator('.dw-canvas').evaluate(element => element.getBoundingClientRect().width);
  assert.ok(canvasWidthFocused > canvasWidthBefore + 100, 'Hiding panels gives meaningful canvas room');
  assert.deepEqual(await selectedIds(), selectedBefore);
  await polishedScreenshot('professional-editor-focus.png');
  await panelToggle.click();
  await page.locator('.dw-sidebar').waitFor({state: 'visible'});
  await page.locator('.dw-inspector').waitFor({state: 'visible'});
  assert.equal(await panelToggle.getAttribute('aria-pressed'), 'false');
  assert.deepEqual(await selectedIds(), selectedBefore);
  assert.equal(await page.locator('.dw-page-list>button.active').innerText(), pageBefore);
  const canvasWidthRestored = await page.locator('.dw-canvas').evaluate(element => element.getBoundingClientRect().width);
  assert.ok(Math.abs(canvasWidthRestored - canvasWidthBefore) <= 1);
  report.focusMode = {canvasWidthBefore, canvasWidthFocused, canvasWidthRestored, selectedIds: selectedBefore, page: pageBefore}; saveReport();
  checks.push('professional-editor-narrow-focus-mode-preserves-page-and-selection');
  await page.setViewportSize(originalViewport);
  checks.push('professional-editor-desktop-and-narrow-no-page-overflow');

  const publish = page.getByTestId('studio-batch-publish');
  await publish.focus(); await page.keyboard.press('Enter'); await dialog().waitFor();
  assert.equal(await dialog().evaluate(element => element.contains(document.activeElement)), true);
  await page.keyboard.press('Tab');
  assert.equal(await dialog().evaluate(element => element.contains(document.activeElement)), true);
  await page.keyboard.press('Shift+Tab');
  assert.equal(await dialog().evaluate(element => element.contains(document.activeElement)), true);
  await dialog().getByLabel('输出格式', {exact: true}).selectOption('pdf');
  await dialog().getByRole('button', {name: '全选', exact: true}).click();
  await page.keyboard.press('Escape'); await dialog().waitFor({state: 'detached'});
  assert.equal(await publish.evaluate(element => element === document.activeElement), true, 'Escape returns focus to the publishing trigger');
  await page.keyboard.press('Enter'); await dialog().waitFor();
  assert.equal(await dialog().getByLabel('输出格式', {exact: true}).inputValue(), 'pdf');
  for (const item of saved.document.pages) assert.equal(await dialog().getByTestId('publish-page-' + item.id).isChecked(), true);
  await polishedScreenshot('professional-publish-configuration.png');
  checks.push('professional-publishing-keyboard-focus-escape-reopen-preserves-selection');

  await dialog().getByTestId('publish-check').click();
  await dialog().getByText('发布检查通过', {exact: true}).waitFor({timeout: 30000});
  await dialog().getByTestId('publish-start').click();
  const link = dialog().getByRole('link', {name: '下载发布文件', exact: true});
  await link.waitFor({timeout: 180000});
  const downloadEvent = page.waitForEvent('download'); await link.click();
  const download = await downloadEvent; assert.equal(await download.failure(), null);
  const pdfPath = path.join(evidence, 'professional-showcase.pdf'); await download.saveAs(pdfPath);
  const pdf = JSON.parse(execFileSync(python, ['-c', "import sys,json;from pypdf import PdfReader;r=PdfReader(sys.argv[1]);print(json.dumps([{'width':float(p.mediabox.width),'height':float(p.mediabox.height),'text':p.extract_text()} for p in r.pages]))", pdfPath], {encoding: 'utf8'}));
  assert.equal(pdf.length, saved.document.pages.length);
  pdf.forEach((item, index) => {
    assert.ok(Math.abs(item.width - saved.document.pages[index].width * .75) < 1);
    assert.ok(Math.abs(item.height - saved.document.pages[index].height * .75) < 1);
    assert.ok(item.text.trim().length > 20, 'PDF must retain real text');
  });
  assert.ok(pdf[0].text.replace(/\s/g, '').includes(edited.replace(/\s/g, '')), 'PDF contains the edited title');
  report.pdf = pdf; saveReport();
  const results = dialog().locator('details.dw-publish-result');
  assert.equal(await results.count(), saved.document.pages.length);
  assert.equal(await results.evaluateAll(items => items.every(item => !item.open)), true, 'Successful per-item detail stays collapsed');
  await results.first().locator('summary').click();
  assert.equal(await results.first().evaluate(element => element.open), true);
  await results.first().locator('summary').click();
  await polishedScreenshot('professional-publish-completed.png');
  await page.keyboard.press('Escape'); await dialog().waitFor({state: 'detached'});
  checks.push('professional-showcase-real-pdf-text-page-count-and-size');

  const exportedEvent = page.waitForResponse(response => new URL(response.url()).pathname === '/api/design/export' && response.request().method() === 'POST');
  const htmlDownloadEvent = page.waitForEvent('download');
  await toolbar().getByRole('button', {name: '导出', exact: true}).click();
  const exportedResponse = await exportedEvent; assert.ok(exportedResponse.ok(), await exportedResponse.text());
  const exported = await exportedResponse.json();
  const htmlDownload = await htmlDownloadEvent; assert.equal(await htmlDownload.failure(), null);
  await htmlDownload.saveAs(path.join(evidence, 'professional-showcase-html.zip'));
  const output = await page.context().newPage();
  try {
    await output.goto(exported.preview_url);
    await output.waitForFunction(() => Boolean(window.LeafLoomStudioInstance));
    assert.equal(await output.evaluate(() => window.STUDIO_DOCUMENT.bindings['atelier.hero'].value), edited);
    for (const variantId of [null, 'en', 'zh-CN', 'ja']) for (const item of saved.document.pages) {
      const exportLabel = item.id + '-' + (variantId || 'source');
      await output.setViewportSize({width: item.width, height: item.height});
      const preflight = await output.evaluate(async ({pageId, variantId}) => {
        const instance = window.LeafLoomStudioInstance;
        instance.update(window.STUDIO_DOCUMENT, {mode: 'static', pageId, variantId});
        await instance.readyForStatic(); return instance.preflight();
      }, {pageId: item.id, variantId});
      const contentGeometry = await output.locator('.studio-stage').evaluate(stage => ({width: stage.clientWidth, height: stage.clientHeight, scrollWidth: stage.scrollWidth, scrollHeight: stage.scrollHeight, roots: [...stage.querySelectorAll('.atelier')].map(element => ({height: element.getBoundingClientRect().height, scrollHeight: element.scrollHeight}))}));
      report.exports.push({pageId: item.id, variantId, preflight, contentGeometry}); saveReport();
      await output.screenshot({path: path.join(evidence, 'professional-showcase-' + exportLabel + '.png'), fullPage: true});
      const outside = await output.locator('.studio-stage').evaluate(stage => {
        const bounds = stage.getBoundingClientRect(), walker = document.createTreeWalker(stage, NodeFilter.SHOW_TEXT), problems = [];
        let node;
        while ((node = walker.nextNode())) {
          if (!node.textContent.trim() || ['STYLE', 'SCRIPT'].includes(node.parentElement?.tagName)) continue;
          const range = document.createRange(); range.selectNodeContents(node);
          for (const box of range.getClientRects()) {
            if (box.width && box.height && (box.left < bounds.left - 2 || box.top < bounds.top - 2 || box.right > bounds.right + 2 || box.bottom > bounds.bottom + 2)) problems.push({text: node.textContent.slice(0, 100), left: box.left, top: box.top, right: box.right, bottom: box.bottom});
          }
        }
        return problems;
      });
      report.exports[report.exports.length - 1].textOutsidePage = outside; saveReport();
    }
  } finally { await output.close(); }
  // Capture all twelve outcomes before failing so one bad headline cannot hide
  // another locale's evidence. This retains both original zero-overflow contracts.
  assert.equal(report.exports.length, saved.document.pages.length * 4);
  const failures = report.exports.flatMap(result => {
    const textOverflow = result.preflight.issues.filter(issue => ['text-overflow', 'text_overflow'].includes(issue.code || issue.kind));
    return textOverflow.length || result.textOutsidePage.length ? [{pageId: result.pageId, variantId: result.variantId, textOverflow, textOutsidePage: result.textOutsidePage}] : [];
  });
  report.exportFailures = failures; saveReport();
  assert.deepEqual(failures, [], 'Every source/locale export must fit its text boxes and keep actual glyph bounds inside the artboard');
  checks.push('professional-showcase-html-real-runtime-all-page-text-bounds');
};
