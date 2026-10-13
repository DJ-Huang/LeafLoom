"""Compile authored translations and verify coverage; no runtime machine translation."""
import json
from pathlib import Path
import re
import ast

ROOT=Path(__file__).resolve().parents[1]
def main():
    values={'zh-CN':{},'en':{},'ja':{}}
    for line in (ROOT/'vault_rag/locales/messages.tsv').read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):continue
        parts=line.split('|')
        if len(parts)!=3:raise ValueError(f'Expected three translations: {line}')
        key,english,japanese=parts
        for language,text in zip(values,(key,english,japanese)):
            values[language][key]=text
        fields=lambda text:set(re.findall(r'\{\w+\}',text))
        if fields(key)!=fields(english) or fields(key)!=fields(japanese):raise ValueError(f'Placeholder mismatch: {key}')
    values['zh-CN']['本地知识库']='LeafLoom · 知织'
    values['zh-CN']['让零散笔记，织成知识。']='让零散笔记，\n织成知识。'
    values['ja']['让零散笔记，织成知识。']='ばらばらのメモを、\n知識へ。'
    values['en']['本地知识库']='LeafLoom'
    values['ja']['本地知识库']='LeafLoom · リーフルーム'
    for language,table in values.items():
        (ROOT/'vault_rag/locales'/f'{language}.json').write_text(json.dumps(table,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    used=[]
    for path in (ROOT/'web/src').glob('*'):
        if path.suffix not in ('.ts','.tsx'):continue
        for literal in re.findall(r'\bt\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')',path.read_text(encoding='utf-8')):
            used.append(ast.literal_eval(literal))
    (ROOT/'.cache/leafloom').mkdir(parents=True,exist_ok=True)
    missing=sorted(set(used)-set(values['en']))
    (ROOT/'.cache/leafloom/missing-messages.json').write_text(json.dumps(missing,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(values["en"])} authored translations; {len(missing)} missing')
    if missing:print('\n'.join(missing))
    return bool(missing)
if __name__=='__main__':raise SystemExit(main())
