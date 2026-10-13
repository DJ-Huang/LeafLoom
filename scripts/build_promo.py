"""Reproducible 35-second product film: actual browser actions, directed camera, original score."""
import json
from pathlib import Path
import shutil
import subprocess
import wave
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from build_brand import icon

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'assets/promo'
WORK=ROOT/'.cache/leafloom/video'
TRANSITION=.3
PUSH_DURATION=.6
SCENES=[
 {'name':'brand','duration':2.5,'caption':'Your knowledge. Your deployment. Your control.'},
 {'name':'write','duration':6.5,'title':'Capture\nan idea.','step':'01 / KEEP YOUR FILES','body':'Write in Markdown.\nKeep the original.','tag':'READ + WRITE','caption':'Capture an idea. Keep your original files.',
  'camera':[(0,1,.5,.5),(PUSH_DURATION,1.03,.5,.5)]},
 {'name':'search','duration':7,'title':'Find it.\nOpen it.','step':'02 / FIND THE SOURCE','body':'Search your knowledge.\nGo straight to the evidence.','tag':'SEARCH + SOURCE','caption':'Find the evidence. Open the source.',
  'camera':[(0,1,.60,.49),(PUSH_DURATION,1.38,.60,.49)]},
 {'name':'graph','duration':7,'title':'Follow the\nconnections.','step':'03 / CONNECT YOUR IDEAS','body':'Focus on one note.\nSee where it leads.','tag':'LINKS + GRAPH','caption':'Focus a note. Explore its connections.',
  'camera':[(0,1,.60,.55),(PUSH_DURATION,1.15,.60,.55)]},
 {'name':'ai-review','duration':5.5,'title':'Review.\nThen save.','step':'04 / OPTIONAL AI','body':'Preview the changes.\nYou decide what stays.','tag':'FICTIONAL AI DEMO','caption':'Optional AI. Preview changes. Accept into a draft.',
  'camera':[(0,1,.63,.50),(PUSH_DURATION,1.15,.63,.50)]},
 {'name':'scope','duration':3.5,'title':'Keep\ncontrol.','step':'05 / YOUR DEPLOYMENT','body':'Run it yourself.\nChoose the search scope.','tag':'LOCAL FIRST','caption':'Your deployment. Your files. Your search scope.',
  'camera':[(0,1,.5,.5),(PUSH_DURATION,1.18,.5,.5)]},
 {'name':'outro','duration':3,'caption':'LeafLoom. Open source. Make it yours.'},
]

def font(size,bold=False):
    for file in [Path('C:/Windows/Fonts')/('segoeuib.ttf' if bold else 'segoeui.ttf'),Path('/System/Library/Fonts/Supplemental')/('Arial Bold.ttf' if bold else 'Arial.ttf'),Path('/usr/share/fonts/truetype/dejavu')/('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')]:
        if file.exists():return ImageFont.truetype(str(file),size)
    raise RuntimeError('Install a readable TrueType font')

def text(draw,xy,value,size=24,color='#FAF9F4',bold=False,spacing=12):
    draw.multiline_text(xy,value,font=font(size,bold),fill=color,spacing=spacing)

def center(draw,value,y,size,color='#244536',bold=False):
    text(draw,((1920-draw.textlength(value,font=font(size,bold)))/2,y),value,size,color,bold)

def background():
    y,x=np.mgrid[0:1080,0:1920];glow=np.exp(-((x-1450)**2/1100000+(y-450)**2/800000))
    pixels=np.stack([19+19*glow,42+32*glow,35+21*glow],axis=-1).astype('uint8')
    im=Image.fromarray(pixels);d=ImageDraw.Draw(im)
    for radius in (340,510,690):d.ellipse((1420-radius,430-radius,1420+radius,430+radius),outline='#305448',width=1)
    mark=icon(46);im.paste(mark,(64,44),mark);text(d,(126,47),'LeafLoom',29,bold=True)
    text(d,(1480,54),'YOUR FILES. CONNECTED.',16,color='#a1bca9')
    return im

def graphics(scene,index):
    name=scene['name'];bg=background()
    if name in ('brand','outro'):
        if name=='outro':
            bg=Image.new('RGB',(1920,1080),'#FAF9F4');d=ImageDraw.Draw(bg)
            mark=icon(105);bg.paste(mark,(907,118),mark);center(d,'LeafLoom',252,52,bold=True)
            center(d,'Make it yours.',365,99,bold=True)
            center(d,'Your knowledge. Your deployment. Your control.',510,36)
            center(d,'OPEN SOURCE  /  MIT  /  WINDOWS + macOS',628,24,color='#647d69')
            center(d,'Run locally. Keep your files. Choose what to share.',760,25,color='#647d69')
            return bg,None
        d=ImageDraw.Draw(bg);text(d,(154,268),'A HOME FOR YOUR IDEAS',21,color='#a9c6b3')
        text(d,(146,332),'LeafLoom',116,bold=True)
        text(d,(154,508),'Weave your notes\ninto knowledge.',52,spacing=9)
        for n,label in enumerate(['YOUR FILES','YOUR DEPLOYMENT','YOUR CONTROL']):
            px=154+n*294;d.rounded_rectangle((px,718,px+272,780),radius=31,fill='#30594a',outline='#628674');text(d,(px+25,734),label,19,bold=True)
        text(d,(154,850),'Local first. Open source. Made for you.',26,color='#a9c6b3')
        mark=icon(270);tile=Image.new('RGBA',(420,420));td=ImageDraw.Draw(tile);td.rounded_rectangle((6,6,414,414),radius=86,fill='#faf9f4');tile.paste(mark,(75,75),mark);bg.paste(tile,(1335,310),tile)
        bg.save(OUTPUT/'cover.png');return bg,None
    shadow=Image.new('RGBA',(1920,1080));sd=ImageDraw.Draw(shadow);sd.rounded_rectangle((432,136,1880,988),radius=24,fill=(0,0,0,150));shadow=shadow.filter(ImageFilter.GaussianBlur(20));bg=Image.alpha_composite(bg.convert('RGBA'),shadow).convert('RGB');d=ImageDraw.Draw(bg)
    d.rounded_rectangle((416,124,1872,970),radius=17,fill='#f6f7f3',outline='#86a493',width=1)
    for n,color in enumerate(['#cfaa95','#d5c59a','#91b6a0']):d.ellipse((434+n*22,137,444+n*22,147),fill=color)
    text(d,(514,130),'LeafLoom  /  Demo vault',14,color='#728577')
    text(d,(64,1004),scene['caption'],23,color='#d8e7dc')
    for n in range(5):d.rounded_rectangle((1570+n*58,1025,1614+n*58,1029),radius=2,fill='#6d9c82' if n<index else '#325448')
    layer=Image.new('RGBA',(360,650));ld=ImageDraw.Draw(layer)
    text(ld,(0,24),scene['step'],17,color='#9ac5a9',bold=True)
    text(ld,(0,96),scene['title'],52 if name!='graph' else 45,bold=True,spacing=5)
    text(ld,(0,295),scene['body'],22,color='#b9cfc0',spacing=12)
    ld.rounded_rectangle((0,424,321,468),radius=22,fill='#315949',outline='#628674');text(ld,(20,432),scene['tag'],16,color='#dfeddf',bold=True)
    text(ld,(0,516),f'{index:02d}',100,color='#456856',bold=True)
    layer.save(WORK/(name+'-label.png'));return bg,WORK/(name+'-label.png')

def smooth(a,b,var):
    u=f'min(1,max(0,({var}-{a:.4f})/{b-a:.4f}))'
    return f'({u}*{u}*(3-2*{u}))'

def curve(points,column,var='on/30'):
    # Exactly two keyframes: one entry push, then a constant crop for the scene.
    result=str(points[0][column])
    for left,right in zip(points,points[1:]):
        delta=right[column]-left[column]
        if delta:result+=f'+({delta:.5f})*{smooth(left[0],right[0],var)}'
    return result

def run(*args):
    result=subprocess.run([str(x) for x in args],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    if result.returncode:raise RuntimeError(result.stderr.decode(errors='replace'))

def soundtrack(takes):
    # Original 120-BPM music: warm pads, plucked notes, bass, drums and action ticks.
    rate=48000;length=35*rate;t=np.arange(length)/rate;mix=np.zeros((length,2));rng=np.random.default_rng(20261013)
    def add(start,value,gain=.1,pan=0):
        at=int(start*rate);end=min(length,at+len(value));value=value[:end-at]*gain
        if end>at:mix[at:end,0]+=value*(1-pan*.35);mix[at:end,1]+=value*(1+pan*.35)
    chords=[(220,261.6256,329.6276),(174.6141,220,261.6256),(130.8128,164.8138,195.9977),(195.9977,246.9417,293.6648)]
    for start in np.arange(0,35,4):
        chord=chords[int(start/4)%4];a=np.arange(int(4.4*rate))/rate;env=np.minimum(1,a/.3)*np.minimum(1,np.maximum(0,4.4-a)/.6)
        for j,f in enumerate(chord):add(start,(np.sin(2*np.pi*f*a)+.15*np.sin(2*np.pi*f*2*a))*env,.045,(j-1)*.7)
    for beat in np.arange(2.5,32,.5):
        a=np.arange(int(.32*rate))/rate;kick=np.sin(2*np.pi*(47*a+19*.035*(1-np.exp(-a/.035))))*np.exp(-a*17);add(beat,kick,.19)
        a=np.arange(int(.12*rate))/rate;noise=rng.standard_normal(len(a));add(beat+.25,(noise-np.roll(noise,1))*np.exp(-a*65),.012,.55)
        if int(round((beat-2.5)*2))%2:
            a=np.arange(int(.16*rate))/rate;add(beat,rng.standard_normal(len(a))*np.exp(-a*35),.025,-.25)
        bass=chords[int(beat/4)%4][0]/2;a=np.arange(int(.4*rate))/rate;add(beat,np.sin(2*np.pi*bass*a)*np.exp(-a*9),.08)
    for n,start in enumerate(np.arange(2.5,32,.25)):
        f=chords[int(start/4)%4][[0,1,2,1,2,1,0,2][n%8]]*2;a=np.arange(int(.6*rate))/rate;env=(1-np.exp(-a*180))*np.exp(-a*7)
        add(start,(np.sin(2*np.pi*f*a)+.22*np.sin(2*np.pi*f*2*a))*env,.035,(-.6,.6)[n%2])
    offset=2.5
    for scene in SCENES[1:-1]:
        take=takes[scene['name']];speed=(scene['duration']+TRANSITION)/take['duration']
        for action in take['actions']:
            a=np.arange(int(.085*rate))/rate;add(offset+action['time']*speed,np.sin(2*np.pi*1100*a)*np.exp(-a*75),.042)
        offset+=scene['duration']
    for cut in [2.5,9,16,23,28.5,32]:
        a=np.arange(int(.35*rate))/rate;noise=np.convolve(rng.standard_normal(len(a)),np.ones(15)/15,mode='same');add(cut-.16,noise*np.sin(np.pi*a/.35)**2,.08)
    mix*=np.minimum(1,t/.6)[:,None]*np.minimum(1,(35-t)/1.2)[:,None];mix=np.tanh(mix)*.85
    with wave.open(str(OUTPUT/'soundtrack.wav'),'wb') as audio:
        audio.setnchannels(2);audio.setsampwidth(2);audio.setframerate(rate);audio.writeframes((mix*32767).astype('<i2').tobytes())

def main():
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):raise RuntimeError('FFmpeg and ffprobe are required')
    take_file=OUTPUT/'recordings/take.json'
    if not take_file.exists():raise RuntimeError('Record real actions with scripts/record_promo.cjs first')
    recorded=json.loads(take_file.read_text())
    assert recorded['language']=='en' and recorded['viewport']==[1600,900] and not recorded['errors']
    takes={s['name']:s for s in recorded['scenes']}
    assert set(takes)=={s['name'] for s in SCENES[1:-1]}
    for take in takes.values():
        source=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(ROOT/take['source'])]))
        stream=next(s for s in source['streams'] if s['codec_type']=='video')
        assert (stream['width'],stream['height'])==(1600,900)
        assert take['duration']>0 and 0<=take['start']<float(source['format']['duration'])
        assert take['start']+take['duration']<=float(source['format']['duration'])+.05
    WORK.mkdir(parents=True,exist_ok=True);clips=[];story=[];srt=[];offset=0
    def clock(value):
        ms=round(value*1000);return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'
    for index,scene in enumerate(SCENES):
        name=scene['name'];duration=scene['duration']+(TRANSITION if index<len(SCENES)-1 else 0)
        bg,label=graphics(scene,index);bg_file=WORK/(name+'-background.png');bg.save(bg_file)
        clip=WORK/(name+'.mp4');clips.append(clip);inputs=['-loop','1','-framerate',30,'-i',bg_file]
        if name in ('brand','outro'):
            graph='[0:v]setsar=1,format=yuv420p[v]'
        else:
            take=takes[name];inputs+=['-ss',take['start'],'-t',take['duration'],'-i',ROOT/take['source'],'-loop','1','-framerate',30,'-i',label]
            points=scene['camera']
            assert len(points)==2 and points[0][0]==0 and points[1][0]==PUSH_DURATION
            assert points[0][2:]==points[1][2:], 'Camera must keep one anchor'
            z=curve(points,1);cx=curve(points,2);cy=curve(points,3)
            x=f'max(0,min(iw-iw/zoom,iw*({cx})-iw/zoom/2))';y=f'max(0,min(ih-ih/zoom,ih*({cy})-ih/zoom/2))'
            graph=f"[1:v]setpts=(PTS-STARTPTS)*{duration/take['duration']:.6f},fps=30,crop=1600:898:0:0,scale=3200:1800,zoompan=z='{z}':x='{x}':y='{y}':d=1:s=1440x810:fps=30,tpad=stop_mode=clone:stop_duration=1[screen];[0:v][screen]overlay=424:154:shortest=1[window];[2:v]format=rgba,fade=t=in:st=0:d=0.3:alpha=1[label];[window][label]overlay=64:253:shortest=1,setsar=1,format=yuv420p[v]"
        run('ffmpeg','-y','-hide_banner','-loglevel','error',*inputs,'-filter_complex',graph,'-map','[v]','-t',duration,'-r',30,'-c:v','libx264','-preset','fast','-crf',18,'-pix_fmt','yuv420p','-an',clip)
        story.append({**scene,'start':offset,'transition':TRANSITION if index<6 else 0,'source':takes[name]['source'] if name in takes else None})
        srt.extend([str(index+1),clock(offset)+' --> '+clock(offset+scene['duration']),scene['caption'],'']);offset+=scene['duration'];print('Rendered '+name,flush=True)
    soundtrack(takes);inputs=[]
    for clip in clips:inputs+=['-i',clip]
    graph=';'.join(f'[{i}:v]settb=AVTB,setpts=PTS-STARTPTS[v{i}]' for i in range(len(clips)));offset=0;current='v0'
    for i in range(1,len(clips)):
        offset+=SCENES[i-1]['duration'];nxt='x'+str(i);graph+=f';[{current}][v{i}]xfade=transition=fade:duration={TRANSITION}:offset={offset}[{nxt}]';current=nxt
    graph+=f';[{current}]format=yuv420p[v]'
    run('ffmpeg','-y','-hide_banner','-loglevel','error',*inputs,'-i',OUTPUT/'soundtrack.wav','-filter_complex',graph,'-map','[v]','-map','7:a','-af','loudnorm=I=-16:TP=-1.5:LRA=9','-c:v','libx264','-preset','fast','-crf',18,'-c:a','aac','-b:a','192k','-ar',48000,'-t',35,'-r',30,'-movflags','+faststart',OUTPUT/'leafloom-en.mp4')
    (OUTPUT/'leafloom-en.srt').write_text('\n'.join(srt),encoding='utf-8');(OUTPUT/'storyboard.json').write_text(json.dumps(story,indent=2)+'\n',encoding='utf-8')
    metadata=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(OUTPUT/'leafloom-en.mp4')]))
    video=next(s for s in metadata['streams'] if s['codec_type']=='video');audio=next(s for s in metadata['streams'] if s['codec_type']=='audio')
    assert (video['width'],video['height'],video['r_frame_rate'],video['codec_name'])==(1920,1080,'30/1','h264')
    assert abs(float(metadata['format']['duration'])-35)<.05 and audio['codec_name']=='aac' and audio['sample_rate']=='48000'
    (WORK.parent/'video-validation.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    print('English product film complete: 35s, 1080p30, real operations, directed camera, original 120-BPM score.')

if __name__=='__main__':main()
