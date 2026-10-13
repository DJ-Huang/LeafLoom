"""Isolated browser-test fixture: python tests/settings_ui_server.py <static build>."""
from pathlib import Path
import sys, logging, os, tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vault_rag.local_state import LocalConfig
from vault_rag.knowledge import Runtime
from vault_rag.web_server import create_app
import uvicorn

# This fixture never uses the user's configured vault or model directories.
temporary=tempfile.TemporaryDirectory(prefix='vault-settings-ui-')
base=Path(temporary.name)
port=int(os.environ.get('VAULT_SETTINGS_TEST_PORT', '18082'))
if port == 18080: raise ValueError('Do not use the production port for UI tests')
static_dir=Path(sys.argv[1]) if len(sys.argv)>1 else Path('/private/tmp/vault-settings-build')
root=base/'vault'
root.mkdir(exist_ok=True)
def put(path, text):
    file=root/path
    file.parent.mkdir(parents=True,exist_ok=True)
    if not file.exists(): file.write_text(text,encoding='utf-8')
put('Notes/知识库首页.md', '''---
title: 知识库首页
verified_status: verified_true
---
# 知识库首页

一个属于自己的知识空间。

## 开始探索

- [[Markdown 示例]]：阅读、公式与任务。
- [[项目规划]]：记录想法，连接资料。
- [交互式网页](../site/index.html)：浏览本地 HTML。

> 好的笔记，让下一次思考有迹可循。
''')
put('Notes/Markdown 示例.md', '''---
title: Markdown 示例
verified_status: verified_true
tags: [知识管理, 演示]
---
# 从记录到连接

让文字、公式与图表自然地出现在同一篇笔记里。

## 今天的想法

- [ ] 整理关于知识检索的资料
- [x] 保留原始 Markdown 文件

阅读 [[项目规划]]，继续探索相关的思路。

## 公式与图表

$$E = mc^2$$

```mermaid
graph LR
 A[本地文件] --> B[知识检索]
 B --> C[可追溯的依据]
```

| 内容 | 用途 |
| --- | --- |
| Markdown | 阅读与记录 |
| RAG | 知识检索 |
| HTML | 交互式预览 |

## 动态目录

```dataview
TABLE file.name
FROM "Notes"
LIMIT 5
```
''')
put('Notes/项目规划.md','---\nverified_status: verified_true\n---\n# 项目规划\n\n知识检索通过关键词、Wiki 与语义连接本地笔记。\n\n## 下一步\n\n先整理证据，再形成判断。\n\n![[Markdown 示例]]\n')
put('Estimation/经验卡.md','---\ndomain: estimation\nverified_status: verified_true\n---\n# 工时评估经验\n\n界面改版工时评估：先梳理导航，再实现组件，最后验证预览与来源。\n')
put('Topics/知识检索.md','---\nmanaged_by: vault-rag\n---\n# 知识检索\n\n[[Markdown 示例]] [[项目规划]]\n')
put('Notes/长文档.md', '# 长文档\n\n'+''.join('## 第 '+str(i)+' 节\n\n'+'知识检索与长文档阅读示例。'*220+'\n\n' for i in range(160))+'## 最后一节\n\n长文档结束标记。\n')
put('Templates/日常记录.md','# 新的记录\n\n{{date}}\n\n{{cursor}}')
put('site/index.html','''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>本地网页预览</title><link rel="stylesheet" href="style.css"></head><body><main><small>LOCAL HTML</small><h1>一个完整的网页空间</h1><p>本地样式、脚本与相对链接保持可用。</p><button id="counter">点击计数 · 0</button><a href="next.html#detail">打开下一页</a><div id="result"></div></main><script src="app.js"></script></body></html>''')
put('site/style.css','body{margin:0;background:#f5f5f1;color:#35352f;font-family:system-ui}main{max-width:760px;margin:80px auto;padding:40px}small{letter-spacing:.2em;color:#999}h1{font-size:42px}p{color:#888;line-height:1.8}button{border:0;border-radius:6px;background:#37352f;color:white;padding:14px 25px;font-size:16px;cursor:pointer}a{display:block;margin-top:25px;color:#555}')
put('site/app.js','let n=0;document.getElementById("counter").onclick=e=>e.target.textContent="点击计数 · "+(++n);fetch("/api/create",{method:"POST",body:JSON.stringify({path:"escaped.md"})}).then(r=>document.getElementById("result").dataset.api=String(r.status)).catch(()=>document.getElementById("result").dataset.api="blocked");')
put('site/next.html','<!doctype html><html><head><link rel="stylesheet" href="style.css"></head><body><main><h1 id="detail">下一页内容</h1><a href="index.html">返回首页</a></main></body></html>')
put('Tasks/记录想法.md','---\nstatus: open\npriority: 高\ndue: 2026-10-15\n---\n# 记录想法\n\n整理新设置页面的交互。')
put('Tasks/完成阅读.md','---\nstatus: done\npriority: 中\ndue: 2026-10-13\n---\n# 完成阅读\n\n阅读项目资料。')
put('Tasks/工作台.base', 'views:\n  - type: table\n    name: 全部任务\n    filters: file.inFolder("Tasks")\n    order: [file.name, status, priority, due]\n  - type: tasknotesKanban\n    name: 任务看板\n    filters: file.inFolder("Tasks")\n  - type: calendar\n    name: 日历\n    dateProperty: due\n    filters: file.inFolder("Tasks")\n')
other=base/'other-vault' 
other.mkdir(exist_ok=True)
(other/'different.md').write_text('# 另一个知识库\n\n独立的内容与检索范围。',encoding='utf-8')
config=LocalConfig(base/'state')
config.save({'root':str(root),'include_roots':[''],'exclude_roots':[],'homepage':'Notes/知识库首页.md','wiki_roots':['Topics'],'estimation_roots':['Estimation'],'templates':'Templates','daily_folder':'Daily','port':port})
runtime=Runtime(config)
runtime.catalog.scan()
def changed(*paths):
    runtime.catalog.apply(list(paths))
    runtime.publish('files', list(paths))
runtime.files.changed=changed
original=runtime.configuration_changed
def configured():
    original()
    runtime.catalog.scan()
runtime.configuration_changed=configured
app=create_app(config,runtime,start_background=False,static_dir=static_dir)
uvicorn.run(app, host='127.0.0.1', port=port,log_level='warning')
