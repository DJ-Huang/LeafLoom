"""Localized, fictional starter vault content shared by onboarding and screenshots."""
from html import escape
import json
from pathlib import Path


COPY = {
    'en': {
        'studio': 'The learning studio', 'intro': 'A small, connected workspace for reading, thinking and making. Every person, project and source in this starter vault is fictional.',
        'project': 'Build a reading ritual', 'lead': 'Turn a quiet corner into a place where good ideas become part of everyday life.',
        'quote': 'Read with a question. Keep one useful idea. Connect it to something you already know.',
        'brief': 'Project at a glance', 'columns': ['Focus', 'Decision', 'Linked notes'],
        'rows': ['Space|A warm light, one chair, fewer distractions', 'Practice|Twenty minutes, four evenings a week', 'Output|One connected note after every session'],
        'steps': 'This week', 'tasks': ['Choose a book and write down one question', 'Set up the reading corner', 'Write a source note in your own words', 'Review the connections on Sunday'],
        'connections': 'Follow the idea', 'map': 'From reading to understanding',
        'home_sections': ['Start here', 'Explore the studio', 'Make it your own'],
        'home_end': 'Edit these examples, reuse the templates, or connect your own folder. Returning to the demo preserves your changes. Search only includes folders you explicitly select.',
        'group_names': ['Concepts', 'Projects', 'Library', 'Journal', 'Guides'],
        'card_sections': ['The idea', 'Try it', 'Connected notes'],
        'card_try': 'Use this idea in the reading project. Write one observation, link the source, and revisit it during the weekly review.',
        'template_names': ['Project brief', 'Reading note', 'Decision record'],
        'template_sections': ['Question or goal', 'Observations and evidence', 'Related notes', 'Next action'],
        'html': ['A field guide to connected thinking', 'Small notes. Bigger ideas.', 'A local reading room for the ideas you want to keep. Follow the path from a question to a note, then from a note to a new connection.', 'THE READING ROOM', 'Read with intention', 'Capture in your words', 'Connect and revisit', 'Ask one clear question before opening a book.', 'Keep a short note and its original source together.', 'Let a weekly review reveal what belongs together.', 'A simple learning loop', 'QUESTION', 'READ', 'NOTE', 'CONNECT', 'WEEKLY PRACTICE', '20 min', 'one quiet session', '1 idea', 'worth remembering', '4 links', 'to explore next', 'Inside this guide', 'The learning loop', 'Reading rituals', 'Sources & connections', 'Your next small step', 'A fictional starter workspace · Works entirely offline'],
        'question': 'How can I turn this reading plan into a habit that lasts?',
        'answer': '**Start with a small loop, not a long reading list.**\n\n1. **Make time visible.** Keep the twenty-minute sessions in [[Notes/04-Project.md|Build a reading ritual]].\n2. **Write one idea in your own words.** Use [[Concepts/Source-notes.md|Source notes]] to keep the source beside your interpretation.\n3. **Connect before collecting more.** Link the idea to [[Concepts/Atomic-notes.md|Atomic notes]] or a current project.\n4. **Return on Sunday.** [[Concepts/Weekly-review.md|Weekly review]] helps you choose what to revisit.\n\n**Next step:** choose one book and write a question for the first session.\n\n*Fictional demo response · No external AI service was called.*',
        'topic': 'DEMO · A reading habit',
    },
    'zh-CN': {
        'studio': '阅读与学习工作室', 'intro': '一个用来阅读、思考与创作的小小知识空间。这个入门知识库中的人物、项目与资料均为虚构示例。',
        'project': '建立自己的阅读习惯', 'lead': '把一个安静的角落，变成让好想法融入日常生活的地方。',
        'quote': '带着问题阅读，用自己的话记录，再连接到已经理解的知识。',
        'brief': '项目一览', 'columns': ['关注点', '当前决定', '关联笔记'],
        'rows': ['空间|一盏暖灯、一把椅子，减少干扰', '习惯|每周四个晚上，每次二十分钟', '产出|每次阅读后，留下一条有连接的笔记'],
        'steps': '本周行动', 'tasks': ['选一本书，写下一个想弄懂的问题', '布置自己的阅读角落', '用自己的话写一条来源笔记', '周日回顾笔记之间的新连接'],
        'connections': '沿着想法继续探索', 'map': '从阅读走向理解',
        'home_sections': ['从这里开始', '探索这个工作室', '变成自己的知识库'],
        'home_end': '可以修改示例、复用模板，或关联自己的目录。再次打开演示库会保留已有修改。只有你明确选择的目录参与检索。',
        'group_names': ['知识卡片', '创作项目', '阅读资料', '学习日志', '使用指南'],
        'card_sections': ['核心想法', '试着实践', '相关笔记'],
        'card_try': '把这个想法用到阅读项目里。记下一条观察，连接原始依据，并在每周回顾时重新审视。',
        'template_names': ['项目简报', '阅读笔记', '决策记录'],
        'template_sections': ['问题或目标', '观察与依据', '相关笔记', '下一步行动'],
        'html': ['连接思考的随身指南', '小小笔记，更大的想法。', '为值得保留的想法，留一间本地阅览室。从一个问题走向一条笔记，再从一条笔记发现新的连接。', '阅读工作室', '带着问题阅读', '用自己的话记录', '连接，然后回顾', '打开一本书之前，先写下一个清晰的问题。', '让简短的笔记与它的原始出处放在一起。', '每周回顾一次，看看哪些想法属于同一条线索。', '一个简单的学习循环', '提问', '阅读', '记录', '连接', '每周练习', '20 分钟', '一段安静的阅读时间', '1 个想法', '值得认真记住', '4 条连接', '等待下一次探索', '本页目录', '学习循环', '阅读习惯', '来源与连接', '下一小步', '虚构入门示例 · 完全离线可用'],
        'question': '怎样把这份阅读计划，变成真正坚持下来的习惯？',
        'answer': '**从一个小循环开始，不必先列很长的书单。**\n\n1. **让时间看得见。** 保留 [[Notes/04-Project.md|阅读习惯项目]] 中每次二十分钟的安排。\n2. **用自己的话写一个想法。** 参考 [[Concepts/Source-notes.md|来源笔记]]，把出处和自己的理解放在一起。\n3. **先连接，再继续收集。** 把想法连接到 [[Concepts/Atomic-notes.md|原子笔记]] 或正在推进的项目。\n4. **周日再回来看看。** 用 [[Concepts/Weekly-review.md|每周回顾]] 决定哪些内容值得重读。\n\n**下一步：** 选一本书，为第一次阅读写下一个问题。\n\n*虚构演示回答 · 未调用外部 AI 服务。*',
        'topic': '演示 · 让阅读成为习惯',
    },
    'ja': {
        'studio': '読書と思考のスタジオ', 'intro': '読む、考える、つくるための小さな知識空間。このサンプルの人物、プロジェクト、資料はすべて架空です。',
        'project': '読書の習慣をつくる', 'lead': '静かな一角を、よいアイデアが日々の暮らしにつながる場所に。',
        'quote': '問いを持って読み、自分の言葉で残し、すでに知っていることにつなげる。',
        'brief': 'プロジェクトの概要', 'columns': ['テーマ', 'いまの決定', '関連するメモ'],
        'rows': ['空間|暖かな照明と椅子で、気が散らない場所に', '習慣|週に四晩、一回二十分', '成果|読むたびに、つながりのあるメモを一つ'],
        'steps': '今週のアクション', 'tasks': ['本を一冊選び、知りたいことを一つ書く', '読書コーナーを整える', '自分の言葉で出典メモを残す', '日曜日に新しいつながりを振り返る'],
        'connections': 'アイデアをたどる', 'map': '読書から理解へ',
        'home_sections': ['ここから始める', 'スタジオを探索', '自分の知識庫に育てる'],
        'home_end': 'サンプルを編集したり、テンプレートを使ったり、自分のフォルダーを接続したりできます。デモを開き直しても変更は残ります。明示的に選んだフォルダーだけを検索します。',
        'group_names': ['知識カード', 'プロジェクト', '読書資料', '学習ログ', '使い方'],
        'card_sections': ['アイデア', '試してみる', '関連するメモ'],
        'card_try': '読書プロジェクトで試しましょう。気づきを一つ書き、出典につなぎ、週の振り返りでもう一度考えます。',
        'template_names': ['プロジェクト概要', '読書メモ', '意思決定の記録'],
        'template_sections': ['問い・目標', '気づきと根拠', '関連するメモ', '次のアクション'],
        'html': ['つながる思考のフィールドガイド', '小さなメモから、大きな発見へ。', '残しておきたいアイデアのための、ローカルの読書室。問いからメモへ、メモから新しいつながりへ。', '読書スタジオ', '問いを持って読む', '自分の言葉で残す', 'つなげて、振り返る', '本を開く前に、知りたいことを一つ書きます。', '短いメモと元の出典を一緒に残します。', '週に一度、アイデア同士のつながりを見直します。', 'シンプルな学習のサイクル', '問う', '読む', '残す', 'つなぐ', '毎週の小さな実践', '20 分', '静かな読書の時間', '1 つ', '覚えておきたいアイデア', '4 本', '次にたどるつながり', 'このページの目次', '学習のサイクル', '読書の習慣', '出典とつながり', '次の小さな一歩', '架空の入門サンプル · 完全オフライン対応'],
        'question': 'この読書プランを、長く続けられる習慣にするには？',
        'answer': '**長い読書リストより、小さなサイクルから始めましょう。**\n\n1. **時間を見える形に。** [[Notes/04-Project.md|読書の習慣]] の一回二十分を続けます。\n2. **自分の言葉で一つ残す。** [[Concepts/Source-notes.md|出典メモ]] で根拠と解釈を一緒に記録します。\n3. **集める前につなげる。** [[Concepts/Atomic-notes.md|アトミックノート]] や進行中のプロジェクトにリンクします。\n4. **日曜日に振り返る。** [[Concepts/Weekly-review.md|週の振り返り]] で読み直す内容を選びます。\n\n**次の一歩：** 本を一冊選び、最初の問いを書きましょう。\n\n*架空のデモ回答 · 外部 AI は呼び出していません。*',
        'topic': 'デモ · 読書の習慣',
    },
}

# Stable paths keep links, previous edits and the existing video workflow usable.
CARDS = [
    ('Concepts/Atomic-notes', ('Atomic notes', '原子笔记', 'アトミックノート'), ('Give each note one clear idea, then let links carry the context.', '一条笔记围绕一个清晰想法，用链接保留上下文。', '一つのメモに一つのアイデアを。背景はリンクでつなぎます。')),
    ('Concepts/Source-notes', ('Source notes', '来源笔记', '出典メモ'), ('Keep what a source says separate from your own interpretation.', '把原始资料的观点与自己的理解分开记录。', '出典の主張と、自分の解釈を分けて残します。')),
    ('Concepts/Active-recall', ('Active recall', '主动回忆', '思い出す練習'), ('Close the book and write what you can explain without looking.', '合上书，写下不看原文也能解释清楚的内容。', '本を閉じ、見ずに説明できることを書きます。')),
    ('Concepts/Spaced-review', ('Spaced review', '间隔回顾', '間隔をあけた復習'), ('Revisit an idea on another day, and record what still feels unclear.', '隔一段时间重新回顾，记录仍然不清楚的地方。', '日をあけて読み直し、まだ曖昧な点を記録します。')),
    ('Concepts/Concept-maps', ('Concept maps', '概念地图', '概念マップ'), ('Name the relationship between ideas instead of merely collecting links.', '不仅收集链接，也写清楚想法之间是什么关系。', 'リンクを集めるだけでなく、関係を言葉にします。')),
    ('Concepts/Weekly-review', ('Weekly review', '每周回顾', '週の振り返り'), ('Choose one question, one useful connection and one next action.', '每周选出一个问题、一条有用的连接和一个下一步。', '問い、役立つつながり、次の行動を一つずつ選びます。')),
    ('Concepts/Deep-reading', ('Deep reading', '专注阅读', '集中して読む'), ('Protect a short session from distractions and follow one question.', '保护一小段不被打扰的时间，围绕一个问题阅读。', '短い時間を確保し、一つの問いに集中して読みます。')),
    ('Concepts/Decision-log', ('Decision log', '决策日志', '意思決定ログ'), ('Record why an option was chosen, and what would change your mind.', '记录为什么选择这个方案，以及什么证据会让你改变决定。', '選んだ理由と、見直すきっかけになる根拠を残します。')),
    ('Projects/Reading-corner', ('A quiet reading corner', '一个安静的阅读角', '静かな読書コーナー'), ('Compare two layouts and choose the smallest setup you will actually use.', '比较两种布置，选一个真正愿意每天使用的简单方案。', '二つの配置を比べ、毎日使える小さな構成を選びます。')),
    ('Projects/Essay', ('An essay from five notes', '从五条笔记写一篇文章', '五つのメモから文章へ'), ('Outline an argument using five connected notes; return to their sources.', '用五条相互连接的笔记搭出论证，再回到各自的来源。', '五つのメモで論点を組み立て、出典を確認します。')),
    ('Projects/Learning-path', ('A four-week learning path', '四周学习路线', '四週間の学習プラン'), ('Alternate reading, explaining, making and reviewing in a small project.', '在一个小项目中交替安排阅读、解释、创作和回顾。', '読む、説明する、つくる、振り返るを交互に進めます。')),
    ('Library/Slow-pages', ('Slow Pages · reading notes', '《慢慢读》· 阅读笔记', '「ゆっくり読む」読書メモ'), ('Fictional source: a short essay about reading with one question at a time.', '虚构资料：一篇讨论每次只带着一个问题阅读的短文。', '架空の資料。一度に一つの問いを持って読む短い随筆です。')),
    ('Library/Small-systems', ('Small Systems · source notes', '《小小系统》· 来源笔记', '「小さな仕組み」出典メモ'), ('Fictional source: observations about making useful routines easy to repeat.', '虚构资料：关于如何让有用的日常习惯更容易重复的观察。', '架空の資料。よい習慣を繰り返しやすくする工夫を扱います。')),
    ('Library/Thinking-in-links', ('Thinking in Links · highlights', '《用连接思考》· 摘录', '「リンクで考える」ハイライト'), ('Fictional source: examples of how a small note becomes part of a larger argument.', '虚构资料：一条小笔记如何成为更大论证的一部分。', '架空の資料。小さなメモを大きな論点につなぐ例を集めます。')),
    ('Library/Questions', ('Questions worth keeping', '值得留下的问题', '残しておきたい問い'), ('Keep open questions beside the notes that may eventually help answer them.', '把尚未解答的问题留在相关笔记旁，等待新的线索。', '未解決の問いを関連メモのそばに置き、新しい手がかりを待ちます。')),
    ('Journal/First-session', ('Session 01 · a fresh start', '第 01 次阅读 · 新的开始', '読書 01 · はじめの一歩'), ('A fictional journal entry: twenty quiet minutes led to one clear question.', '虚构日志：二十分钟的安静阅读，留下了一个更清晰的问题。', '架空のログ。静かな二十分から、問いが一つ生まれました。')),
    ('Journal/New-connection', ('Session 02 · a new connection', '第 02 次阅读 · 新的连接', '読書 02 · 新しいつながり'), ('A fictional journal entry: a source note changed an earlier project decision.', '虚构日志：一条来源笔记，让先前的项目决定有了新的方向。', '架空のログ。出典メモから、プロジェクトの決定を見直しました。')),
    ('Journal/Sunday-review', ('Sunday · look back, move forward', '周日 · 回顾，再前进', '日曜日 · 振り返って次へ'), ('A fictional journal entry: keep three notes, clarify one link, choose one next step.', '虚构日志：保留三条笔记，澄清一条连接，选择一个下一步。', '架空のログ。三つのメモを残し、一つの関係を確かめ、次の一歩を選びます。')),
    ('Guides/Markdown', ('Writing with Markdown', '用 Markdown 记录', 'Markdown で書く'), ('Use headings, tables, task lists and wiki links while keeping plain text files.', '使用标题、表格、任务清单和双链，正文依然是普通文本文件。', '見出し、表、タスク、リンクを使い、本文はプレーンテキストで保ちます。')),
    ('Guides/HTML', ('Your local HTML reading room', '本地 HTML 阅览室', 'ローカル HTML の読書室'), ('Open [[Web/index.html|the field guide]] inside the workspace. Its stylesheet and illustrations are local companion files.', '在工作区打开 [[Web/index.html|连接思考指南]]。样式和插图均来自本地文件。', '[[Web/index.html|思考のガイド]] をワークスペース内で開きます。スタイルと図はローカルに保存しています。')),
    ('Guides/AI', ('Discuss a note with AI', '围绕笔记与 AI 对话', 'メモを AI と話し合う'), ('Attach a note or a short selection, ask a focused question, and review suggestions before saving.', '附上当前笔记或一段选文，提出具体问题，检查建议后再保存。', 'メモや選択した文章を添え、具体的に質問し、提案を確認して保存します。')),
]


def extend_examples(root: Path):
    for index, (locale, c) in enumerate(COPY.items()):
        folder = root / locale
        titles = {path: names[index] for path, names, _ in CARDS}
        def link(path):
            return f'[[{path}|{titles.get(path, c["project"])}]]'
        def put(path, title, body, category='demo'):
            target = folder / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f'---\ntitle: {title}\nverified_status: limited\ntags: [leafloom, demo, {category}]\n---\n# {title}\n\n{body}\n', encoding='utf-8')

        groups = list(dict.fromkeys(path.split('/')[0] for path, _, _ in CARDS))
        for pos, (path, names, descriptions) in enumerate(CARDS):
            group = path.split('/')[0]
            peers = [p for p, _, _ in CARDS if p.startswith(group + '/') and p != path]
            related = list(dict.fromkeys([*peers[:2], 'Notes/04-Project', CARDS[(pos + 5) % len(CARDS)][0], 'Concepts/Weekly-review']))
            related = [p for p in related if p != path]
            put(path + '.md', names[index], f'## {c["card_sections"][0]}\n\n{descriptions[index]}\n\n## {c["card_sections"][1]}\n\n{c["card_try"]}\n\n## {c["card_sections"][2]}\n\n' + '\n'.join('- ' + link(p) for p in related), group.lower())

        table = '| ' + ' | '.join(c['columns']) + ' |\n| --- | --- | --- |\n'
        for row, target in zip(c['rows'], ['Projects/Reading-corner', 'Concepts/Deep-reading', 'Concepts/Source-notes']):
            table += '| ' + row.replace('|', ' | ') + f' | [{titles[target]}](../{target}.md) |\n'
        body = c['lead'] + '\n\n> ' + c['quote'] + '\n\n## ' + c['brief'] + '\n\n' + table
        body += '\n## ' + c['steps'] + '\n\n' + '\n'.join(('- [x] ' if i == 0 else '- [ ] ') + task for i, task in enumerate(c['tasks']))
        body += '\n\n## ' + c['connections'] + '\n\n' + ' · '.join(link(p) for p in ['Concepts/Atomic-notes', 'Concepts/Active-recall', 'Concepts/Weekly-review'])
        put('Notes/04-Project.md', c['project'], body, 'project')

        home = c['intro'] + '\n\n> ' + c['quote'] + '\n\n## ' + c['home_sections'][0] + '\n\n- ' + link('Notes/04-Project') + '\n- [[Web/index.html|' + c['html'][0] + ']]\n\n## ' + c['home_sections'][1] + '\n\n'
        for group, title in zip(groups, c['group_names']):
            home += '### ' + title + '\n\n' + '\n'.join('- ' + link(p) for p, _, _ in CARDS if p.startswith(group + '/')) + '\n\n'
        home += '## ' + c['home_sections'][2] + '\n\n' + c['home_end']
        put('00-Home.md', c['studio'], home)

        for name, title in zip(['Project', 'Reading', 'Decision'], c['template_names']):
            content = '# {{date}} · ' + title + '\n\n' + '\n\n'.join('## ' + heading + '\n\n' + ('{{cursor}}' if i == 0 else '-') for i, heading in enumerate(c['template_sections'])) + '\n'
            (folder / 'Templates' / (name + '.md')).write_text(content, encoding='utf-8')
        write_html(folder / 'Web', locale, c)
        manifest_path = folder / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest.update(question=c['question'], answer=c['answer'], topic_title=c['topic'], showcase={'markdown': 'Notes/04-Project.md', 'html': 'Web/index.html'})
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def write_html(folder: Path, locale: str, c: dict):
    folder.mkdir(exist_ok=True)
    h = [escape(text) for text in c['html']]
    cards = ''.join(f'<section><span class="number">0{i+1}</span><h3>{h[4+i]}</h3><p>{h[7+i]}</p></section>' for i in range(3))
    nodes = ''.join(f'<g><circle cx="{x}" cy="84" r="30"/><text x="{x}" y="89">{h[11+i]}</text></g>' for i, x in enumerate([70, 245, 420, 595]))
    stats = ''.join(f'<div><strong>{h[16+i*2]}</strong><span>{h[17+i*2]}</span></div>' for i in range(3))
    folder.joinpath('index.html').write_text(f'''<!doctype html>
<html lang="{locale}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{h[0]}</title><link rel="stylesheet" href="studio.css"></head>
<body><aside class="sidebar"><div class="monogram">L<span> / </span>S</div><strong>LEAFLOOM<br>STUDIO</strong><p>{h[3]}</p><nav><a href="#intro">01 &nbsp; {h[23]}</a><a href="#loop">02 &nbsp; {h[24]}</a><a href="#practice">03 &nbsp; {h[25]}</a><a href="#next">04 &nbsp; {h[26]}</a></nav><small>{h[27]}</small></aside>
<main><header><span>FIELD NOTES &nbsp; / &nbsp; 001</span><span>READ · THINK · CONNECT</span></header><article id="intro"><p class="eyebrow">{h[0]}</p><h1>{h[1]}</h1><p class="lead">{h[2]}</p><div class="cards">{cards}</div><div class="diagram" id="loop"><div class="diagram-heading"><span>01 / {h[10]}</span><span>LEARNING BY CONNECTING</span></div><svg viewBox="0 0 665 170" role="img" aria-label="{h[10]}"><path d="M100 84H215M275 84H390M450 84H565"/><path class="return" d="M595 116V145H70V116"/>{nodes}</svg></div><div class="practice" id="practice"><p class="eyebrow">{h[15]}</p><div class="stats">{stats}</div></div><footer id="next">{escape(c['quote'])}</footer></article></main></body></html>''', encoding='utf-8')
    folder.joinpath('studio.css').write_text('''*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#faf8f1;color:#263e35;font:15px/1.7 system-ui,-apple-system,sans-serif}.sidebar{position:fixed;inset:0 auto 0 0;width:205px;padding:36px 26px;background:#eeeee3;border-right:1px solid #dfe2d4}.monogram{font:48px Georgia,serif;color:#245b48;margin-bottom:14px}.monogram span{color:#a0ab94;font-size:32px}.sidebar strong{font-size:16px;line-height:1.5;letter-spacing:3px}.sidebar p{font-size:12px;color:#71806c;margin-top:18px}.sidebar nav{display:grid;gap:22px;margin-top:45px}.sidebar a{font-size:12px;text-decoration:none;color:#4f6658}.sidebar small{position:absolute;bottom:24px;left:26px;right:26px;font-size:10px;color:#7e8873}main{margin-left:205px}header{height:66px;border-bottom:1px solid #e1e4d6;display:flex;justify-content:space-between;align-items:center;padding:0 42px;font-size:10px;letter-spacing:1.4px;color:#77856e}article{padding:34px 42px;max-width:1250px;margin:auto}.eyebrow{font-size:10px;letter-spacing:2px;color:#9a704b;text-transform:uppercase;margin:0 0 12px}h1{font:clamp(28px,3.4vw,47px)/1.2 Georgia,"Songti SC",serif;letter-spacing:-1px;margin:0 0 18px}.lead{color:#657463;max-width:720px;font-size:14px;margin:0 0 28px}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-bottom:26px}.cards section{border-top:1px solid #ccd4c2;padding-top:12px}.number{font:italic 20px Georgia,serif;color:#a1ad93}h3{font-size:14px;margin:7px 0}.cards p{font-size:12px;color:#75806e;margin:0}.diagram{border:1px solid #d6decc;border-radius:12px;background:#e8efdf;padding:18px 24px}.diagram-heading{display:flex;justify-content:space-between;font-size:10px;color:#607653;letter-spacing:1px}.diagram-heading span:last-child{color:#95a285;font-size:8px}.diagram svg{width:100%;height:160px;display:block}.diagram circle{fill:#fcfcf6;stroke:#8da280;stroke-width:1.2}.diagram path{stroke:#7d9873;stroke-width:1.5;fill:none}.diagram .return{stroke-dasharray:4 5;stroke:#a4b497}.diagram text{text-anchor:middle;fill:#395741;font:11px system-ui}.practice{padding-top:25px}.stats{display:flex;gap:65px}.stats div{display:flex;flex-direction:column}.stats strong{font:29px Georgia,serif;color:#31543e}.stats span{font-size:11px;color:#7c8974}footer{margin-top:24px;padding-top:16px;border-top:1px solid #e1e4d6;color:#7b866e;font-size:11px}@media(max-width:800px){.sidebar{width:160px;padding:24px 18px}main{margin-left:160px}article{padding:26px}header{padding:0 26px}.cards{gap:12px}.stats{gap:30px}.diagram-heading span:last-child{display:none}}@media(max-width:560px){.sidebar{display:none}main{margin:0}.cards{grid-template-columns:1fr}header span:last-child{display:none}.stats{gap:24px}}
''', encoding='utf-8')
