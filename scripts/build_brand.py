"""Reproducible vector and desktop brand assets (Pillow is a build tool only)."""
from pathlib import Path
from PIL import Image, ImageDraw
ROOT=Path(__file__).resolve().parents[1]
SVG='''<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><rect x="2" y="2" width="60" height="60" rx="16" fill="#245C48"/><path d="M32 21C25 16 17 15 12 17V44C19 42 26 44 32 48C38 44 45 42 52 44V17C46 15 39 16 32 21Z" fill="#FBF7ED"/><path d="M32 22V47M19 25L26 28L20 37M26 28L43 25L44 36" stroke="#8AAE93" fill="none" stroke-width="2" stroke-linecap="round"/><g fill="#245C48"><circle cx="19" cy="25" r="3"/><circle cx="26" cy="28" r="3"/><circle cx="20" cy="37" r="3"/><circle cx="43" cy="25" r="3"/><circle cx="44" cy="36" r="3"/></g></svg>'''
def icon(size=1024):
    # Supersampled geometry matches the SVG mark; exports contain no raster edits.
    scale=size/64
    image=Image.new('RGBA',(size,size));draw=ImageDraw.Draw(image)
    box=lambda points:tuple(round(x*scale) for x in points)
    draw.rounded_rectangle(box((2,2,62,62)),radius=round(16*scale),fill='#245C48')
    # Sample the cubic book outline directly from the canonical geometry.
    def curve(start,a,b,end):
        return [((1-t)**3*start[0]+3*(1-t)**2*t*a[0]+3*(1-t)*t*t*b[0]+t**3*end[0],(1-t)**3*start[1]+3*(1-t)**2*t*a[1]+3*(1-t)*t*t*b[1]+t**3*end[1]) for t in [i/32 for i in range(33)]]
    points=curve((32,21),(25,16),(17,15),(12,17))+[(12,44)]+curve((12,44),(19,42),(26,44),(32,48))+curve((32,48),(38,44),(45,42),(52,44))+[(52,17)]+curve((52,17),(46,15),(39,16),(32,21))
    draw.polygon([box(point) for point in points],fill='#FBF7ED')
    for line in [[(32,22),(32,47)],[(19,25),(26,28),(20,37)],[(26,28),(43,25),(44,36)]]:draw.line([box(p) for p in line],fill='#8AAE93',width=round(2*scale),joint='curve')
    for x,y in [(19,25),(26,28),(20,37),(43,25),(44,36)]:draw.ellipse(box((x-3,y-3,x+3,y+3)),fill='#245C48')
    return image
def main():
    output=ROOT/'assets/brand';output.mkdir(parents=True,exist_ok=True)
    (output/'logo.svg').write_text(SVG,encoding='utf-8')
    (output/'logo-monochrome.svg').write_text(SVG.replace('#245C48','#111111').replace('#8AAE93','#111111').replace('#FBF7ED','#ffffff'),encoding='utf-8')
    image=icon();image.save(output/'logo.png');image.save(output/'leafloom.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
    image.save(output/'leafloom.icns')
    for size in (32,64,256):image.resize((size,size),Image.Resampling.LANCZOS).save(output/f'icon-{size}.png')
    public=ROOT/'web/public';public.mkdir(exist_ok=True);(public/'favicon.svg').write_text(SVG,encoding='utf-8')
if __name__=='__main__':main()
