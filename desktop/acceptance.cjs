'use strict';
// Exercise the installed App through its own Chromium debugger, not a browser shell.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');
const {spawn, execFileSync} = require('node:child_process');
const {once} = require('node:events');
const options = {};
for (let i = 2; i < process.argv.length; i++) {
  const key = process.argv[i].replace(/^--/, '');
  options[key] = process.argv[i + 1]?.startsWith('--') || !process.argv[i + 1] ? true : process.argv[++i];
}
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(fn, timeout = 90000) {
  const end = Date.now() + timeout; let error;
  while (Date.now() < end) { try { const value = await fn(); if (value) return value; } catch (e) { error = e; } await sleep(250); }
  throw error || new Error('验收等待超时');
}
async function port() {
  const server = net.createServer(); server.listen(0, '127.0.0.1'); await once(server, 'listening');
  const value = server.address().port; await new Promise(resolve => server.close(resolve)); return value;
}
class Debugger {
  constructor(socket) { this.socket = socket; this.sequence = 0; this.pending = new Map();
    socket.addEventListener('message', event => { const value = JSON.parse(event.data); const pending = this.pending.get(value.id); if (!pending) return; this.pending.delete(value.id); clearTimeout(pending.timer); value.error ? pending.reject(new Error(value.error.message)) : pending.resolve(value.result); });
    socket.addEventListener('close', () => {
      for (const pending of this.pending.values()) {clearTimeout(pending.timer); pending.reject(new Error('App 验收连接已关闭'));}
      this.pending.clear();
    });
  }
  async send(method, params = {}) {
    const id = ++this.sequence;
    const result = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {this.pending.delete(id); reject(new Error('App 验收请求超时：' + method));}, 15000);
      this.pending.set(id, {resolve, reject, timer});
    });
    this.socket.send(JSON.stringify({id, method, params})); return result;
  }
  async evaluate(expression) {
    const value = await this.send('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
    if (value.exceptionDetails) throw new Error(value.exceptionDetails.text + ': ' + (value.exceptionDetails.exception?.description || expression));
    return value.result.value;
  }
}
async function main() {
  // macOS /var is an alias for /private/var. Match LocalConfig.save's canonical root.
  const fixture = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'VaultRag-桌面验收-')));
  const home = path.join(fixture, '私有 状态'); fs.mkdirSync(path.join(home, 'desktop'), {recursive: true});
  fs.writeFileSync(path.join(home, 'desktop/settings.json'), JSON.stringify({migrationComplete: true, autostart: false}));
  fs.writeFileSync(path.join(home, 'preferences.json'), JSON.stringify({locale: 'zh-CN', onboarding: {}}));
  const root = path.join(fixture, '中文 知识库'); fs.mkdirSync(path.join(root, 'RAG/Notes'), {recursive: true});
  fs.writeFileSync(path.join(root, 'RAG/Notes/release.md'), '# 安装包验收\n\n桌面本地知识库。[[linked]]\n');
  fs.writeFileSync(path.join(root, 'RAG/Notes/linked.md'), '# 图谱关联笔记\n');
  fs.writeFileSync(path.join(root, 'RAG/Notes/preview.html'), '<h1>HTML 验收</h1><script>document.body.dataset.executed="yes"</script>');
  const servicePort = await port(), debugPort = await port(), mainDebugPort = await port(), origin = 'http://127.0.0.1:' + servicePort;
  fs.writeFileSync(path.join(home, 'config.json'), JSON.stringify({root, revision: 'acceptance', port: servicePort,
    include_roots: ['RAG'], exclude_roots: [], rules_roots: ['RAG/Rules'], wiki_roots: ['RAG/Navigation'], estimation_roots: ['RAG/EstimationDB'],
    write_targets: {notes: 'RAG/Notes', rules: 'RAG/Rules', navigation: 'RAG/Navigation', estimation: 'RAG/EstimationDB'}, homepage: 'RAG/Notes/release.md', templates: 'Templates', daily_folder: 'Daily'}));
  if (options['reuse-model-from']) {
    fs.cpSync(path.join(path.resolve(options['reuse-model-from']), 'models'), path.join(home, 'models'), {recursive: true, filter: file => !file.split(path.sep).includes('.cache')});
  }
  const env = {...process.env, VAULT_RAG_HOME: home, PYTHONUTF8: '1',
    // Hide developer runtimes while retaining Windows' built-in ACL/UI tools.
    PATH: process.platform === 'win32' ? [process.env.SystemRoot, path.join(process.env.SystemRoot, 'System32'), path.join(process.env.SystemRoot, 'System32/WindowsPowerShell/v1.0')].join(path.delimiter) : '/usr/bin:/bin:/usr/sbin:/sbin'};
  if (!options['with-model']) env.HF_HUB_OFFLINE = '1';
  let executable = options.app ? path.resolve(options.app) : null;
  let backend, child, cdp, mainCdp, installer = options.installer ? path.resolve(options.installer) : null;
  const report = {platform: process.platform, architecture: process.arch, fixture, installed_from: installer,
    global_tools_hidden: true, checks: [], pending: ['原生目录选择对话框', 'PDF与文件保存对话框', '登录后的自动启动', '保存冲突时的退出提示', '覆盖升级及卸载'], passed: false};
  function passed(check) { report.checks.push(check); console.log('PASS:', check); }
  try {
    if (installer) {
      if (process.platform === 'darwin') {
        const mount = path.join(fixture, 'mount'); fs.mkdirSync(mount);
        execFileSync('/usr/bin/hdiutil', ['attach', installer, '-readonly', '-nobrowse', '-mountpoint', mount], {env, stdio: 'pipe'});
        const appBundle = path.join(fixture, 'Applications/LeafLoom.app');
        try { execFileSync('/usr/bin/ditto', [path.join(mount, 'LeafLoom.app'), appBundle]); }
        finally { execFileSync('/usr/bin/hdiutil', ['detach', mount], {stdio: 'pipe'}); }
        executable = path.join(appBundle, 'Contents/MacOS/LeafLoom');
        backend = path.join(appBundle, 'Contents/Resources/backend/vault-rag-backend');
      } else if (process.platform === 'win32') {
        execFileSync(installer, ['/S'], {env, stdio: 'pipe'});
        // Builder stores InstallLocation in its private key. The uninstall entry
        // uses 'LeafLoom <version>' and contains a quoted uninstall executable.
        const script = "$x=Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*' | Where-Object { $_.DisplayName -like 'LeafLoom *' } | Select-Object -First 1; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); if ($x.UninstallString -match '^\"([^\"]+)\"') { [IO.Path]::GetDirectoryName($Matches[1]) }";
        const installDir = execFileSync('powershell.exe', ['-NoProfile', '-Command', script], {encoding: 'utf8'}).trim();
        if (!installDir) throw new Error('没有找到实际安装目录');
        executable = path.join(installDir, 'VaultRag.exe'); backend = path.join(installDir, 'resources/backend/vault-rag-backend.exe');
        assert.ok(fs.existsSync(executable), '实际安装的 App 可执行文件存在');
      } else throw new Error('不支持此平台的安装验收');
      passed('实际安装包安装完成');
    }
    if (!executable) throw new Error('需要 --installer 或 --app');
    if (!backend) backend = process.platform === 'darwin' ? path.resolve(executable, '../../Resources/backend/vault-rag-backend') : path.join(path.dirname(executable), 'resources/backend/vault-rag-backend.exe');
    const result = JSON.parse(execFileSync(backend, ['self-check'], {env, cwd: fixture, encoding: 'utf8'}).trim().split('\n').at(-1));
    assert.ok(result.ok); passed('安装后 Torch、LanceDB、MCP 和内置资源检查');
    const log = fs.openSync(path.join(fixture, 'app-output.log'), 'a');
    child = spawn(executable, ['--remote-debugging-port=' + debugPort, '--inspect=' + mainDebugPort], {env, cwd: fixture, stdio: ['ignore', log, log]});
    fs.closeSync(log);
    const request = async (route, body, method) => {
      const token = fs.readFileSync(path.join(home, 'auth-token'), 'utf8').trim();
      const response = await fetch(origin + route, {method: method || (body ? 'POST' : 'GET'),
        headers: {Authorization: 'Bearer ' + token, 'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(4000)});
      return {status: response.status, body: await response.json()};
    };
    const status = await until(async () => { const response = await request('/api/status'); return response.status === 200 && response.body.distribution === 'desktop' && response.body; });
    const instance = status.desktop_instance_id;
    const target = await until(async () => (await (await fetch('http://127.0.0.1:' + debugPort + '/json')).json()).find(target => target.type === 'page' && target.url.startsWith(origin + '/')));
    const socket = new WebSocket(target.webSocketDebuggerUrl); await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, {once: true}); socket.addEventListener('error', reject, {once: true}); });
    cdp = new Debugger(socket);
    const mainTarget = await until(async () => (await (await fetch('http://127.0.0.1:' + mainDebugPort + '/json')).json())[0]);
    const mainSocket = new WebSocket(mainTarget.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {mainSocket.addEventListener('open', resolve, {once: true}); mainSocket.addEventListener('error', reject, {once: true});});
    mainCdp = new Debugger(mainSocket);
    await until(() => cdp.evaluate('!!window.vaultDesktop && !!document.querySelector(".sidebar-shortcuts")'));
    assert.equal(await cdp.evaluate('typeof require'), 'undefined');
    assert.equal(await cdp.evaluate('window.vaultDesktop.getAutostart()'), false);
    passed('独立 App 窗口、受限桌面接口和默认关闭登录启动');
    if (!options['with-model']) {
      await until(() => cdp.evaluate('document.querySelector(".model-preparation button")?.textContent === "重试下载"'));
      await cdp.evaluate('document.querySelector(".model-preparation button").click()');
      await until(() => cdp.evaluate('document.querySelector(".model-preparation button")?.textContent === "重试下载"'));
      passed('首次模型下载失败可重试，App 继续提供浏览和编辑');
    }
    const second = spawn(executable, ['--background'], {env, cwd: fixture, stdio: 'ignore'});
    const [secondCode] = await once(second, 'exit'); assert.equal(secondCode, 0);
    assert.equal((await request('/api/status')).body.desktop_instance_id, instance); passed('重复启动复用同一后台');
    const windowExpression = 'process.mainModule.require("electron").BrowserWindow.getAllWindows()[0]';
    assert.equal(await mainCdp.evaluate(windowExpression + '.isVisible()'), true);
    await mainCdp.evaluate(windowExpression + '.close(); true');
    await until(async () => (await mainCdp.evaluate(windowExpression + '.isVisible()')) === false, 10000);
    assert.equal((await request('/api/status')).body.desktop_instance_id, instance);
    const reopened = spawn(executable, [], {env, cwd: fixture, stdio: 'ignore'});
    assert.equal((await once(reopened, 'exit'))[0], 0);
    await until(() => mainCdp.evaluate(windowExpression + '.isVisible()'), 10000);
    passed('关闭窗口继续后台运行，重新打开恢复 App 窗口');
    const session = (await request('/api/session')).body;
    await cdp.send('Page.navigate', {url: origin + '/?note=RAG%2FNotes%2Frelease.md'});
    await until(() => cdp.evaluate('!!document.querySelector("button[title=源码]")'));
    await cdp.evaluate('document.querySelector("button[title=源码]").click()');
    await until(() => cdp.evaluate('!!document.querySelector(".cm-content")'));
    await cdp.evaluate('document.querySelector(".cm-content").focus()');
    await cdp.send('Input.insertText', {text: '桌面编辑验收\n'});
    await until(async () => (await request('/api/file?path=RAG%2FNotes%2Frelease.md')).body.text.includes('桌面编辑验收'), 15000);
    passed('App 内编辑和自动保存');
    const screenshot = await cdp.send('Page.captureScreenshot', {format: 'png'});
    const screenshotFile = path.join(__dirname, 'release', 'acceptance-' + process.platform + '.png');
    fs.mkdirSync(path.dirname(screenshotFile), {recursive: true});
    fs.writeFileSync(screenshotFile, Buffer.from(screenshot.data, 'base64'));
    report.screenshot = path.basename(screenshotFile);
    await cdp.send('Page.navigate', {url: origin + '/?view=graph'});
    await until(() => cdp.evaluate('!!document.querySelector(".graph canvas") && document.querySelector(".graph")?.getAttribute("aria-busy") === "false"'));
    assert.ok((await request('/api/graph')).body.links.length > 0);
    passed('App 内关系图谱完成渲染');
    const stale = (await request('/api/file?path=RAG%2FNotes%2Frelease.md')).body;
    fs.appendFileSync(path.join(root, 'RAG/Notes/release.md'), '\n外部修改');
    assert.equal((await request('/api/file', {path: stale.path, root, text: '不应覆盖', etag: stale.etag}, 'PUT')).status, 409);
    passed('外部修改保留与版本冲突拒绝覆盖');
    const preview = (await request('/api/html-preview', {path: 'RAG/Notes/preview.html', root, text: fs.readFileSync(path.join(root, 'RAG/Notes/preview.html'), 'utf8')})).body.url;
    await cdp.evaluate(`window.open(${JSON.stringify(origin + preview)}, '_blank'); true`);
    const previewTarget = await until(async () => (await (await fetch('http://127.0.0.1:' + debugPort + '/json')).json()).find(target => target.url.includes('/html-preview/')));
    const previewSocket = new WebSocket(previewTarget.webSocketDebuggerUrl); await new Promise(resolve => previewSocket.addEventListener('open', resolve, {once: true}));
    const previewDebugger = new Debugger(previewSocket);
    assert.equal(await previewDebugger.evaluate('typeof window.vaultDesktop'), 'undefined');
    assert.equal(await previewDebugger.evaluate('document.body.dataset.executed'), 'yes');
    previewSocket.close(); passed('HTML 预览执行与桌面权限隔离');
    const token = fs.readFileSync(path.join(home, 'auth-token'), 'utf8').trim();
    const mcp = await fetch(origin + '/mcp', {method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', Authorization: 'Bearer ' + token},
      body: JSON.stringify({jsonrpc: '2.0', id: 1, method: 'initialize', params: {protocolVersion: '2025-03-26', capabilities: {}, clientInfo: {name: 'desktop-acceptance', version: '1'}}})});
    assert.equal(mcp.status, 200); assert.ok((await mcp.json()).result); passed('安装后的 HTTP MCP 初始化');
    if (options['with-model']) {
      await until(async () => (await request('/api/status')).body.model.prepared, 1800000);
      passed(options['reuse-model-from'] ? '复用已有完整模型' : '首次模型准备完成');
      if (options['reuse-model-from']) report.pending.push('首次模型联网下载（本次复用已有模型）');
    } else report.pending.push('首次模型联网下载与推理（本次使用离线失败场景）');
    const maintenance = spawn(executable, ['--prepare-update'], {env, cwd: fixture, stdio: 'pipe'});
    // An attached Node inspector otherwise waits for its debugger before final process exit.
    mainCdp.socket.close(); mainCdp = null;
    const [exitCode] = await once(maintenance, 'exit'); assert.equal(exitCode, 0);
    await until(() => child.exitCode !== null, 20000); passed('升级前保存并正常停止后台');
    assert.equal(fs.readFileSync(path.join(root, 'RAG/Notes/release.md'), 'utf8').includes('外部修改'), true);
    assert.equal(fs.existsSync(path.join(home, 'auth-token')), true); passed('退出保留笔记和私有配置');
    if (options['with-model']) {
      const inference = JSON.parse(execFileSync(backend, ['model-check', '--home', home], {env: {...env, HF_HUB_OFFLINE: '1'}, cwd: fixture, encoding: 'utf8', timeout: 300000}).trim().split('\n').at(-1));
      assert.equal(inference.dimension, 1024); passed('安装包内 BGE-M3 离线推理');
    }
    report.passed = true;
  } catch (error) { report.error = error.stack; throw error; }
  finally {
    report.app_exit_code = child?.exitCode;
    if (!report.passed) {
      report.logs = {};
      for (const file of [path.join(fixture, 'app-output.log'), path.join(home, 'logs/desktop-process.log'), path.join(home, 'logs/desktop-backend.log')]) {
        if (fs.existsSync(file)) report.logs[path.basename(file)] = fs.readFileSync(file, 'utf8').slice(-12000);
      }
    }
    cdp?.socket.close();
    mainCdp?.socket.close();
    if (child && child.exitCode === null) {
      // Ask for a normal stop. Never forcibly terminate the backend during a failed check.
      spawn(executable, ['--prepare-update'], {env, cwd: fixture, stdio: 'ignore'});
      report.pending.push('失败后后台停止状态需要检查：' + fixture);
    }
    const output = path.resolve(options.output || path.join(__dirname, 'release/acceptance-' + process.platform + '.json'));
    fs.mkdirSync(path.dirname(output), {recursive: true}); fs.writeFileSync(output, JSON.stringify(report, null, 2));
    console.log('Acceptance report:', output);
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
