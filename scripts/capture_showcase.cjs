// Real product screenshots from packaged demo content, never a user's service.
'use strict';
const {chromium} = require('../desktop/node_modules/playwright-core');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = process.env.LEAFLOOM_DEMO_URL || 'http://127.0.0.1:18089';
assert.equal(base, 'http://127.0.0.1:18089', 'Only the isolated promo fixture is permitted');
const locales = ['en', 'zh-CN', 'ja'];

async function main() {
  const browser = await chromium.launch({headless: true, channel: process.env.LEAFLOOM_BROWSER_CHANNEL || 'chrome'});
  const errors = [], captures = [];
  try {
    for (const locale of locales) {
      const context = await browser.newContext({viewport: {width: 1800, height: 1125}, deviceScaleFactor: 1, locale, reducedMotion: 'reduce'});
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(locale + ': ' + error.message));
      const catalog = require('../vault_rag/locales/' + locale + '.json');
      const text = key => catalog[key] || key;
      await page.goto(base, {waitUntil: 'domcontentloaded'});
      await page.locator('main').first().waitFor();
      const fixture = await page.evaluate(async locale => {
        const session = await (await fetch('/api/session')).json();
        assertDemo(session);
        function assertDemo(session) {if (!session.demo) throw new Error('Not the isolated screenshot fixture');}
        const response = await fetch('/api/promo/seed', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Vault-CSRF': session.csrf}, body: JSON.stringify({locale, showcase: true})});
        if (!response.ok) throw new Error('Demo setup failed');
        return response.json();
      }, locale);
      assert(fixture.root.includes('LeafLoom Studio'));
      // Let the real background index loop settle after switching the fixture
      // root. Requests during its idle grace period would postpone that work.
      await page.waitForTimeout(6500);
      await page.evaluate(({root, topic}) => localStorage.setItem('ai-topic:' + root, topic), fixture);
      const open = async file => {
        await page.goto(base + '/?note=' + encodeURIComponent(file), {waitUntil: 'domcontentloaded'});
        await page.locator('.document:visible').waitFor();
        await page.waitForFunction(locale => document.documentElement.lang === locale, locale);
      };
      const expand = async folder => {
        const row = page.getByRole('treeitem').filter({has: page.locator('.tree-label > span', {hasText: new RegExp('^' + folder + '$')})});
        if (await row.getAttribute('aria-expanded') === 'false') await row.locator('.tree-label').click();
      };
      const openProject = async () => {
        await open(fixture.showcase.markdown);
        await expand('Notes');
        await page.locator('.directory-tree .tree-label').filter({hasText: '04-Project.md'}).click();
        await page.locator('.document:visible .markdown h1').waitFor();
      };
      const shot = async name => {
        await page.evaluate(async () => {await document.fonts.ready;});
        await page.waitForTimeout(350);
        const visible = await page.locator('body').innerText();
        assert(!/\/(?:Users|home|private|var\/folders)\/|auth-token|Bearer\s+[a-f0-9]{20}/i.test(visible), 'Private path or token in screenshot');
        assert(!(await page.locator('.index-status').innerText()).includes(text('请先在网页关联一个本地目录')), 'Demo initialization has not settled');
        const output = path.resolve('assets/screenshots', locale, name + '.png');
        await page.screenshot({path: output, animations: 'disabled'});
        captures.push(locale + '/' + name + '.png');
      };

      await openProject();
      await page.getByRole('button', {name: text('文档信息'), exact: true}).click();
      assert.equal(await page.locator('.document:visible .markdown table tbody tr').count(), 3);
      assert.equal(await page.locator('.document:visible .markdown table a').count(), 3);
      assert.equal(await page.locator('.document:visible .markdown input[type=checkbox]').count(), 4);
      await shot('showcase-markdown');

      await expand('Concepts');
      await page.getByRole('button', {name: text('关系图谱'), exact: true}).click();
      await page.locator('.graph[aria-busy=false]').waitFor();
      await page.waitForTimeout(900);
      const graph = await page.evaluate(async () => (await fetch('/api/graph')).json());
      assert(graph.nodes.length >= 27 && graph.links.length >= 70, 'Demo graph is incomplete');
      // Use the real graph controls; keep the full network in view.
      await page.getByRole('button', {name: text('适应画布'), exact: true}).click();
      for (let i = 0; i < 2; i++) await page.getByRole('button', {name: text('放大图谱'), exact: true}).click();
      await shot('showcase-graph');

      await openProject();
      await page.getByRole('button', {name: text('AI 对话'), exact: true}).click();
      await page.locator('.ai-answer .markdown').waitFor();
      await page.locator('.ai-demo-banner').waitFor();
      await page.locator('.ai-messages').evaluate(element => {element.scrollTop = 0;});
      assert(await page.locator('.ai-answer a').count() >= 3, 'AI demo should reference actual starter notes');
      await shot('showcase-ai');
      await page.getByRole('button', {name: text('关闭 AI 面板'), exact: true}).click();

      await open(fixture.showcase.html);
      await expand('Web');
      await page.locator('.directory-tree .tree-label').filter({hasText: 'index.html'}).click();
      const frame = page.frameLocator('.html-preview-frame');
      await frame.locator('h1').waitFor();
      await frame.locator('svg').waitFor();
      assert.equal(await frame.locator('.cards section').count(), 3);
      assert(await frame.locator('body').evaluate(element => getComputedStyle(element).backgroundColor) === 'rgb(250, 248, 241)', 'Local HTML companion stylesheet did not load');
      await shot('showcase-html');
      await context.close();
    }
    assert.deepEqual(errors, []);
    fs.mkdirSync('.cache/leafloom', {recursive: true});
    const result = {captures, rendererErrors: errors, fixture: 'Packaged fictional starter vault; external AI disabled; no user data'};
    fs.writeFileSync('.cache/leafloom/showcase-validation.json', JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result));
  } finally {
    await browser.close();
  }
}
main().catch(error => {console.error(error); process.exitCode = 1;});
