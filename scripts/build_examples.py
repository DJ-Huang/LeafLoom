"""Author the public, fictional example vaults used by onboarding and media."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'vault_rag/examples'
DATA={
 'en':{
  'home':'A place for your ideas','intro':'This is a fictional demo. Explore freely: these files belong to this example folder.',
  'names':['Capture an idea','Find it again','Connect the dots','A small creative project','Think with AI'],
  'tagline':'Your files. Your ideas. Connected.',
  'capture':'Start small. Write one idea in plain Markdown. Keep useful links, add a few tags, and let the note grow. Your original files stay where they are.',
  'retrieve':'Knowledge search combines keywords, semantic search when the local model is ready, and topic links. Open the source before drawing a conclusion. Search only the folders you select.',
  'connect':'Link related ideas with [[01-Capture]] and [[02-Retrieve]]. The knowledge graph reveals paths between notes, helping you return to the context of an idea.',
  'project':'A fictional weekend project: design a reading corner. Capture inspiration, collect materials, compare options, and keep decisions linked to their sources.',
  'ai':'AI is optional. Your configured CLI and model service can receive the question, selected text and current note. Review suggested edits before saving them to your files.',
  'sections':['A thought worth keeping','Next steps','Related ideas','Explore the example','Small habits, lasting knowledge'],
  'tasks':['Capture a useful idea','Find the source','Connect a related note'],'query':'ideas',
  'question':'How can I turn scattered notes into useful knowledge?',
  'answer':'Start with a small habit: capture one useful idea, find it again, then connect it to another note. [[Notes/01-Capture.md]] explains how to write a clear note, while [[Notes/03-Connect.md]] shows how links preserve context. This is a fictional demonstration, not a live AI response.'},
 'zh-CN':{
  'home':'让想法有一个归处','intro':'这是完全虚构的演示知识库。可以自由探索：这些文件只属于示例目录。',
  'names':['记下一个想法','再次找到它','连接知识的线索','一个小小的创作计划','和 AI 一起思考'],
  'tagline':'自己的文件，连接每一次思考。',
  'capture':'从一个小想法开始。用普通 Markdown 记录，保留有用的链接，添加几个标签，让笔记慢慢生长。原始文件始终保留在自己的目录里。',
  'retrieve':'知识检索结合关键词、模型准备完成后的本地语义检索，以及主题链接。形成结论前先打开原文，核对上下文。只有明确选择的目录参与检索。',
  'connect':'通过 [[01-Capture]] 和 [[02-Retrieve]] 把相关想法连接起来。关系图谱让笔记之间的路径变得清晰，帮助我们找回一个想法的来处。',
  'project':'一个虚构的周末计划：设计自己的阅读角落。记下灵感，收集材料，比较不同方案，再把每个决定连接到原始依据。',
  'ai':'AI 是可选能力。配置的 CLI 与模型服务可能接收问题、选中文字和当前笔记。AI 提出修改后，先检查建议，再手动保存到自己的文件。',
  'sections':['值得留下的想法','接下来','相关线索','探索这个示例','小小的习惯，长久的知识'],
  'tasks':['记下一个有用的想法','找到原文依据','连接相关笔记'],'query':'想法',
  'question':'如何把零散笔记变成有用的知识？',
  'answer':'从一个小习惯开始：记下一个有用的想法，再次找到它，然后连接相关笔记。[[Notes/01-Capture.md]] 介绍怎样清晰记录，[[Notes/03-Connect.md]] 展示如何用链接保留上下文。这是虚构演示，不是真实 AI 回答。'},
 'ja':{
  'home':'アイデアの居場所','intro':'これは架空のデモ知識庫です。自由に試してください。ファイルはこのサンプル専用です。',
  'names':['アイデアを残す','もう一度見つける','知識をつなぐ','小さな創作プロジェクト','AI と考える'],
  'tagline':'自分のファイルで、思考をつなぐ。',
  'capture':'小さなアイデアから始めましょう。普通の Markdown で記録し、役立つリンクとタグを添えて、メモを育てます。元のファイルは自分のフォルダーに残ります。',
  'retrieve':'知識検索はキーワード、モデル準備後のローカル意味検索、トピックのリンクを組み合わせます。結論を出す前に原文を開いて確認しましょう。選択したフォルダーだけを検索します。',
  'connect':'[[01-Capture]] と [[02-Retrieve]] で関連するアイデアをつなぎます。知識グラフでメモ同士の道筋が見え、アイデアの背景をたどれます。',
  'project':'架空の週末プロジェクト：読書コーナーを作る。ひらめきを記録し、素材を集め、案を比較して、決定と根拠をつなぎましょう。',
  'ai':'AI は任意です。設定した CLI とモデルサービスには質問、選択した文章、現在のメモが送られることがあります。提案された変更を確認し、手動で保存してください。',
  'sections':['残しておきたいアイデア','次のステップ','関連するメモ','サンプルを探索','小さな習慣が、長く役立つ知識に'],
  'tasks':['役立つアイデアを記録する','原文の根拠を見つける','関連するメモをつなぐ'],'query':'アイデア',
  'question':'ばらばらのメモを役立つ知識にするには？',
  'answer':'小さな習慣から始めましょう。役立つアイデアを記録し、見つけ直し、関連するメモにつなぎます。[[Notes/01-Capture.md]] は記録の方法を、[[Notes/03-Connect.md]] はリンクで背景を残す方法を紹介します。これは架空のデモで、実際の AI の回答ではありません。'}
}
def build():
 for locale,d in DATA.items():
  root=ROOT/locale;root.mkdir(parents=True,exist_ok=True)
  files=['01-Capture','02-Retrieve','03-Connect','04-Project','05-AI']
  def put(path,title,body):
   p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(f'---\ntitle: {title}\nverified_status: limited\ntags: [leafloom, demo]\n---\n# {title}\n\n'+body+'\n',encoding='utf-8')
  links='\n'.join(f'- [[Notes/{f}|{name}]]' for f,name in zip(files,d['names']))
  put('00-Home.md',d['home'],f'> {d["tagline"]}\n\n{d["intro"]}\n\n## {d["sections"][3]}\n\n{links}\n\n## {d["sections"][4]}\n\n'+ '\n'.join('- [ ] '+x for x in d['tasks']))
  for i,(file,key) in enumerate(zip(files,['capture','retrieve','connect','project','ai'])):
   related='\n'.join(f'- [[{files[j]}|{d["names"][j]}]]' for j in range(5) if j!=i)
   put(f'Notes/{file}.md',d['names'][i],d[key]+f'\n\n## {d["sections"][0]}\n\n> {d["tagline"]}\n\n## {d["sections"][1]}\n\n'+ '\n'.join('- [ ] '+x for x in d['tasks'])+f'\n\n## {d["sections"][2]}\n\n{related}')
  p=root/'Templates/Note.md';p.parent.mkdir(exist_ok=True);p.write_text('# {{date}}\n\n{{cursor}}\n',encoding='utf-8')
  (root/'manifest.json').write_text(json.dumps({'homepage':'00-Home.md','query':d['query'],'question':d['question'],'answer':d['answer']},ensure_ascii=False,indent=2),encoding='utf-8')
 from example_studio import extend_examples
 extend_examples(ROOT)
if __name__=='__main__':build()
