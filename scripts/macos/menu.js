// AppKit compatibility menu until the maintained ARM64/macOS 14 binary is built.
// Uses the system Objective-C bridge, never loads an embedding model.
ObjC.import('AppKit');
ObjC.import('Foundation');

function run(argv) {
    var repo = argv[0], state = argv[1], task = null;
    var fm = $.NSFileManager.defaultManager;
    var app = $.NSApplication.sharedApplication;
    app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
    function text(path) {
        var value = $.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, null);
        return value.isNil() ? '' : ObjC.unwrap(value);
    }
    var labels = [];
    function tr(key) {
        var language = 'auto';
        try { language = JSON.parse(text(state + '/preferences.json')).locale || 'auto'; } catch (_) {}
        if (language === 'auto') language = ObjC.unwrap($.NSLocale.preferredLanguages.objectAtIndex(0));
        var code = language.indexOf('zh') === 0 ? 'zh-CN' : language.indexOf('ja') === 0 ? 'ja' : 'en';
        try { return JSON.parse(text(repo + '/vault_rag/locales/' + code + '.json'))[key] || key; } catch (_) { return key; }
    }
    function alert(message) {
        var box = $.NSAlert.alloc.init;
        box.messageText = tr('服务操作失败'); box.informativeText = message;
        box.runModal;
    }
    function execute(action) {
        if (task && task.running) return;
        try {
            task = $.NSTask.alloc.init;
            task.launchPath = repo + '/.venv/bin/python';
            task.arguments = ['-X', 'utf8', '-m', 'vault_rag.cli', 'service', action];
            task.currentDirectoryPath = repo;
            var environment = ObjC.deepUnwrap($.NSProcessInfo.processInfo.environment);
            environment.VAULT_RAG_HOME = state; task.environment = environment;
            var log = state + '/logs/menubar-actions.log';
            if (!fm.fileExistsAtPath(log)) fm.createFileAtPathContentsAttributes(log, $.NSData.data, null);
            var output = $.NSFileHandle.fileHandleForWritingAtPath(log);
            output.seekToEndOfFile; task.standardOutput = output; task.standardError = output;
            task.launch;
        } catch (error) { task = null; alert(String(error)); }
    }
    ObjC.registerSubclass({
        name: 'VaultRagCompatibilityMenu', superclass: 'NSObject',
        methods: {
            'openWeb:': {types: ['void', ['id']], implementation: function () { execute('open'); }},
            'startService:': {types: ['void', ['id']], implementation: function () { execute('start'); }},
            'stopService:': {types: ['void', ['id']], implementation: function () { execute('stop'); }},
            'restartService:': {types: ['void', ['id']], implementation: function () { execute('restart'); }},
            'openLogs:': {types: ['void', ['id']], implementation: function () {
                $.NSWorkspace.sharedWorkspace.openURL($.NSURL.fileURLWithPath(state + '/logs'));
            }},
            'quitMenu:': {types: ['void', ['id']], implementation: function () { app.terminate(null); }},
            'refresh:': {types: ['void', ['id']], implementation: function () { refresh(); }}
        }
    });
    var target = $.VaultRagCompatibilityMenu.alloc.init;
    var item = $.NSStatusBar.systemStatusBar.statusItemWithLength($.NSVariableStatusItemLength);
    item.button.image = $.NSImage.alloc.initWithContentsOfFile(repo + '/assets/brand/icon-64.png');
    item.button.image.size = $.NSMakeSize(20, 20);
    item.button.title = ' ○';
    var menu = $.NSMenu.alloc.initWithTitle(tr('本地知识库'));
    menu.autoenablesItems = false;
    function entry(title, selector) {
        var value = $.NSMenuItem.alloc.initWithTitleActionKeyEquivalent(tr(title), selector || null, '');
        if (selector) value.target = target; else value.enabled = false;
        menu.addItem(value); if (selector) labels.push([value,title]); return value;
    }
    var status = entry('正在检查服务…'), detail = entry('');
    menu.addItem($.NSMenuItem.separatorItem);
    entry('打开网页', 'openWeb:'); entry('刷新状态', 'refresh:');
    menu.addItem($.NSMenuItem.separatorItem);
    entry('启动服务', 'startService:'); entry('停止服务', 'stopService:'); entry('重启服务', 'restartService:');
    menu.addItem($.NSMenuItem.separatorItem);
    entry('查看日志文件夹', 'openLogs:'); entry('退出菜单栏（服务继续运行）', 'quitMenu:');
    item.menu = menu;
    function refresh() {
        labels.forEach(function(pair) { pair[0].title = tr(pair[1]); });
        if (fm.fileExistsAtPath(state + '/menubar.stop')) { app.terminate(null); return; }
        if (task && task.running) { status.title = tr('处理中…'); return; }
        if (task) {
            if (task.terminationStatus !== 0) alert(tr('查看日志') + ': ' + state + '/logs/menubar-actions.log');
            task = null;
        }
        try {
            var savedConfig = text(state + '/config.json');
            var config = savedConfig ? JSON.parse(savedConfig) : {port: 18080};
            var request = $.NSMutableURLRequest.requestWithURL($.NSURL.URLWithString('http://127.0.0.1:' + config.port + '/api/status'));
            request.timeoutInterval = 3;
            request.setValueForHTTPHeaderField('Bearer ' + text(state + '/auth-token').trim(), 'Authorization');
            var response = Ref(), error = Ref();
            var data = $.NSURLConnection.sendSynchronousRequestReturningResponseError(request, response, error);
            if (data.isNil() || response[0].statusCode !== 200) throw Error('Service unavailable');
            var value = JSON.parse(ObjC.unwrap($.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding)));
            status.title = tr('服务运行中 · HTTP MCP');
            detail.title = (value.num_files || 0) + ' ' + tr('篇') + ' · ' + tr((value.sync || {}).state || '检查中') + ' · ' + tr((value.model || {}).loaded ? '模型已加载' : '模型未加载');
            item.button.title = ' ●';
        } catch (_) {
            status.title = tr('服务未响应 / 已停止'); detail.title = tr('点击启动服务恢复'); item.button.title = ' ○';
        }
        item.button.toolTip = status.title;
    }
    var timer = $.NSTimer.scheduledTimerWithTimeIntervalTargetSelectorUserInfoRepeats(5, target, 'refresh:', null, true);
    refresh(); app.run;
    timer.invalidate;
}
