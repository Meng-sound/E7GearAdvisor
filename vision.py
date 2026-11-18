"""针对用户实机截图校准的制作总览/强化面板读取；低匹配图标拒识。"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import tempfile
import base64
import io
import unicodedata
import hashlib,copy
from collections import OrderedDict
from fast_vision import ranked

from PIL import Image, ImageOps, ImageDraw, ImageFont

from core import Gear, Stat, parse_text, parse_stat, _clean
from screen_metadata import read_metadata,official_score_lines
from panel_reader import try_inventory,try_floating_detail,augment_names,color_grade
from stat_rows import read_stat_rows,isolate_game_window
from reforge_reader import try_reforge
from adaptive_reader import header_metadata
from craft_locator import locate_crafted_cards
from layout_router import page_hint
from set_icons import match_set_badge

ROOT = Path(__file__).resolve().parent


def signature(image, size=24):
    grey = ImageOps.grayscale(image)
    minimum, maximum = grey.getextrema()
    if maximum < 45 or maximum - minimum < 25:
        return None
    threshold = minimum + (maximum - minimum) * .38
    mask = grey.point(lambda x: 255 if x > threshold else 0)
    bounds = mask.getbbox()
    if not bounds:
        return None
    # 图标外的空白不能改变签名；统一缩放后保留抗锯齿轮廓。
    cropped = mask.crop(bounds).resize((size, size), Image.Resampling.LANCZOS)
    return list(cropped.getdata())


def cosine(a, b):
    if not a or not b:
        return 0.0
    norm = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x, y in zip(a, b)) / norm if norm else 0


def match_icon(image, templates, threshold=.80, margin=.025):
    sig = signature(image)
    if sig is None:
        return None, 0
    scores = ranked(sig,templates)
    if scores is None:scores=sorted(((cosine(sig,v),key) for key,values in templates.items() for v in values),reverse=True)
    if not scores:
        return None, 0
    best, key = scores[0]
    other = next((s for s, k in scores if k != key), 0)
    if best < threshold or best - other < margin:
        return None, best
    return key, best

def match_stat_icon(image,x,y,templates):
    first=match_icon(image.crop((x,y,x+32,y+30)),templates)
    if first[0] is not None and first[1]>=.88:return first
    wide=match_icon(image.crop((x,y-2,x+40,y+36)),templates,threshold=.82,margin=.035)
    if wide[0] is not None and (first[0] is None or wide[1]>first[1]+.06):return wide
    return first


def normalise(image):
    image = isolate_game_window(image)
    if image.size==(1821,1055):return image
    # 标题栏与16:9内容分开归一化，让窗口缩放和仅客户端截图使用同一布局。
    if image.width>900:
        def light_row(y):
            samples=[image.getpixel((x,y)) for x in range(50,image.width-50,max(1,image.width//30))]
            return samples and sum(min(p)>170 and max(p)-min(p)<40 for p in samples)/len(samples)>.75
        title=0
        if image.height>50 and light_row(8):
            for y in range(1,min(90,image.height)):
                if light_row(y):title=y+1
                elif y>15:break
        elif 12<image.height-image.width*9/16<85:
            title=round(image.height-image.width*9/16)
        client=image.crop((0,title,image.width,image.height))
        if 1.68<client.width/client.height<1.87:
            client=client.resize((1821,1025),Image.Resampling.LANCZOS)
            image=Image.new('RGB',(1821,1055),'#050b13');image.paste(client,(0,30))
            return image
    if image.width != 1821:
        image = image.resize((1821, round(image.height * 1821 / image.width)), Image.Resampling.LANCZOS)
    return image


def find_cards(image):
    """检测装备彩色边框连通块，不根据本张图的固定十个位置硬编码卡片。"""
    small = image.resize((image.width // 2, image.height // 2))
    width, height = small.size
    px = small.load()
    mask = set()
    for y in range(int(height * .24), int(height * .80)):
        for x in range(int(width * .045), int(width * .95)):
            r, g, b = px[x, y]
            blue = b > 65 and b > r * 1.3 and b > g * 1.1
            purple = r > 50 and b > 40 and r > g * 1.5 and b > g * 1.5
            red = r > 55 and r > g * 2 and r > b * 1.4
            if blue or purple or red:
                mask.add((x, y))
    found = []
    while mask:
        stack = [mask.pop()]
        points = []
        while stack:
            x, y = stack.pop()
            points.append((x, y))
            for n in [(x+1,y), (x-1,y), (x,y+1), (x,y-1)]:
                if n in mask:
                    mask.remove(n)
                    stack.append(n)
        if len(points) < 60:
            continue
        xs, ys = zip(*points)
        box = (min(xs)*2, min(ys)*2, (max(xs)+1)*2, (max(ys)+1)*2)
        w, h = box[2]-box[0], box[3]-box[1]
        if 88 < w < 170 and 88 < h < 170:
            # 稀有/英雄装备角标会向右下延伸；外框左上角稳定。
            if not any(abs(box[0]-b[0]) < 25 and abs(box[1]-b[1]) < 25 for b in found):
                found.append(box)
    ordered = sorted(found, key=lambda b: (b[1],b[0]))
    groups = []
    for box in ordered:
        group = next((g for g in groups if abs(g[0][1]-box[1]) < 30), None)
        if group is None:
            groups.append([box])
        else:
            group.append(box)
    aligned = []
    for group in groups:
        top = min(b[1] for b in group)
        for b in sorted(group,key=lambda b:b[0]):
            aligned.append((b[0],top,b[2],b[3]))
    return aligned


def grade_at(image, x, y):
    counts = {'稀有': 0, '英雄': 0, '史诗': 0}
    for dx in range(1, 6):
        for dy in range(12, 95):
            r, g, b = image.getpixel((x+dx, y+dy))[:3]
            if b > 60 and b > r*1.4:
                counts['稀有'] += 1
            elif r > 45 and b > 35 and r > g*1.7 and b > g*1.5:
                counts['英雄'] += 1
            elif r > 50 and r > g*1.5 and r > b*1.8:
                counts['史诗'] += 1
    grade = max(counts, key=counts.get)
    return grade if counts[grade] >= 15 else ''


def field_box(x, y, index):
    # level/main/sub1/sub2/sub3/sub4/画面黄色分数。
    boxes = [(4, 5, 43, 34), (175, 1, 241, 40),
             (175, 49, 239, 86), (280, 49, 345, 86),
             (175, 85, 239, 121), (280, 85, 345, 121), (294, 1, 340, 39)]
    a,b,c,d = boxes[index]
    return (x+a,y+b,x+c,y+d)


def number_mask(image, yellow=False):
    rgb = image.convert('RGB')
    out = Image.new('L',rgb.size)
    values=[]
    for r,g,b in rgb.getdata():
        yes = (r>140 and g>105 and b<175 and r>g*.85) if yellow else (min(r,g,b)>50 and max(r,g,b)-min(r,g,b)<42)
        values.append(255 if yes else 0)
    out.putdata(values)
    return out


def glyphs(image):
    px=image.load(); spans=[]; start=None
    for x in range(image.width):
        present=any(px[x,y] for y in range(image.height))
        if present and start is None:
            start=x
        if not present and start is not None:
            spans.append((start,x));start=None
    if start is not None:
        spans.append((start,image.width))
    result=[]
    for a,b in spans:
        glyph=image.crop((a,0,b,image.height));box=glyph.getbbox()
        if not box:
            continue
        glyph=glyph.crop(box)
        if sum(v>0 for v in glyph.getdata())<7 or glyph.height<7:
            continue
        result.append((list(glyph.resize((16,24),Image.Resampling.LANCZOS).getdata()),glyph.width/glyph.height))
    return result


def template_number(image, templates, yellow=False):
    parts=glyphs(number_mask(image,yellow))
    if not parts:
        return None
    chars=[]; confidence=1
    for shape,ratio in parts:
        scores=ranked(shape,templates,ratio)
        if scores is None:
            scores=[]
            for char,examples in templates.items():
                for sample in examples:scores.append((cosine(shape,sample['shape'])-.10*abs(math.log(ratio/sample['ratio'])),char))
            scores.sort(reverse=True)
        best,char=scores[0]
        other=next((s for s,c in scores if c!=char),0)
        if best<.80 or best-other<.02:
            return None
        chars.append(char);confidence=min(confidence,best)
    text=''.join(chars)
    if not re.fullmatch(r'\d{1,4}%?',text):
        return None
    return (float(text.rstrip('%')),text.endswith('%'),text)


def read_number_tiles(image, cards, ocr, directory,needed=None):
    if hasattr(ocr,'recognize_tiles'):
        tiles=[];positions=[]
        for row,box in enumerate(cards):
          for col in range(7):
            if needed is not None and (row,col) not in needed:continue
            raw=image.crop(field_box(*box[:2],col));tile=number_mask(raw,yellow=col in {0,6});bounds=tile.getbbox()
            if bounds and bounds[3]-bounds[1]>=7:
                tiles.append(raw.convert('RGB'));positions.append((row,col))
        if not tiles:return {}
        values=ocr.recognize_tiles(tiles);numbers={};retry=[]
        for position,(raw,confidence) in zip(positions,values):
            text=unicodedata.normalize('NFKC',raw).replace(' ','');m=re.fullmatch(r'(\d{1,4}(?:\.\d+)?)(%?)',text)
            if m and confidence>=.85:numbers[position]=(float(m.group(1)),bool(m.group(2)),text)
            else:retry.append(positions.index(position))
        if retry:
            cropped=[tiles[i].crop((5,0,tiles[i].width,tiles[i].height)) for i in retry]
            for i,(raw,confidence) in zip(retry,ocr.recognize_tiles(cropped)):
                text=unicodedata.normalize('NFKC',raw).replace(' ','');m=re.fullmatch(r'(\d{1,4}(?:\.\d+)?)(%?)',text)
                if m and confidence>=.85:numbers[positions[i]]=(float(m.group(1)),bool(m.group(2)),text)
        return numbers
    montage = Image.new('RGB', (7*170, len(cards)*110), '#050b13')
    for row, box in enumerate(cards):
        x,y = box[:2]
        for col in range(7):
            tile = image.crop(field_box(x,y,col))
            tile.thumbnail((70,40))
            tile = tile.resize((tile.width*2,tile.height*2), Image.Resampling.LANCZOS)
            montage.paste(tile, (col*170+8,row*110+12))
    path = Path(directory) / 'number-tiles.png'
    montage.save(path)
    result = ocr.request(path=str(path))
    words = [w for line in result['lines'] for w in line.get('words',[])]
    grouped = {}
    for w in words:
        row = int((w['y']+w['h']/2)//110)
        col = int((w['x']+w['w']/2)//170)
        grouped.setdefault((row,col), []).append(w)
    numbers = {}
    for rc, group in grouped.items():
        text = ''.join(w['text'] for w in sorted(group,key=lambda w:w['x']))
        text = unicodedata.normalize('NFKC',text).replace(' ','')
        # 无法可靠解析时留空，不能给缺失数字填0。
        m = re.fullmatch(r'[^0-9]*([0-9]{1,4}(?:\.[0-9]+)?)(%?)[^0-9]*',text)
        if m:
            numbers[rc] = (float(m.group(1)),bool(m.group(2)),text)
    return numbers


class ScreenReader:
    PANEL_REGIONS={'inventory-right':(1210,220,1780,880),'hero-equipment-popup':(637,89,1190,942)}
    def __init__(self, ocr):
        self.ocr = ocr
        self.templates = json.loads((ROOT/'data/icon-signatures.json').read_text(encoding='utf-8'))
        self._frames=OrderedDict();self.frame_hits=0
        self._panel_frames=OrderedDict();self._panel_keys={};self.panel_hits=0

    def remember(self,key,value):
        self._frames[key]=copy.deepcopy(value)
        if len(self._frames)>6:self._frames.popitem(last=False)
        layout=value.get('layout');panel_key=self._panel_keys.get(layout)
        if panel_key is not None:
            self._panel_frames[panel_key]=copy.deepcopy(value);self._panel_frames.move_to_end(panel_key)
            if len(self._panel_frames)>6:self._panel_frames.popitem(last=False)
        return value

    def read(self, request, mode='auto', slot='头盔',on_captured=None):
        if hasattr(self.ocr,'begin_frame'):self.ocr.begin_frame()
        with tempfile.TemporaryDirectory(prefix='e7-vision-') as td:
            if request.get('path'):
                source = request['path']
            else:
                source = str(Path(td)/'frame.png')
                self.ocr.request(rect=request['rect'],save_to=source,capture_only=True)
                if on_captured:on_captured()
            with Image.open(source) as original:
                image = normalise(original) if original.width > 900 else original.convert('RGB')
            if request.get('character_read'):
                from character_reader import read_character_request
                return read_character_request(image,self.ocr,td,self.catalog,request.get('hero_id'))
            region=image.crop((100,120,1770,835)) if mode=='batch' else image
            frame_key=(mode,slot,image.size,hashlib.blake2b(region.tobytes(),digest_size=16).digest())
            if frame_key in self._frames:
                self.frame_hits+=1;value=copy.deepcopy(self._frames[frame_key]);value['cache_hit']=True;return value
            self._panel_keys={}
            if mode!='batch' and image.size==(1821,1055):
                header=image.crop((0,30,550,150)).tobytes()
                for layout,box in self.PANEL_REGIONS.items():
                    digest=hashlib.blake2b(header+image.crop(box).tobytes(),digest_size=16).digest()
                    panel_key=(mode,slot,layout,image.size,digest);self._panel_keys[layout]=panel_key
                    if panel_key in self._panel_frames:
                        self.panel_hits+=1;self._panel_frames.move_to_end(panel_key);value=copy.deepcopy(self._panel_frames[panel_key]);value['cache_hit']=True;value['cache_scope']='equipment-panel';return value
            hint=page_hint(image,self.ocr,td) if mode!='batch' and image.width>900 else None
            if mode!='batch' and image.width>900:
                if hint not in {'inventory','enhance'}:
                    floating=try_floating_detail(image,self.ocr,td)
                    if floating:
                        return self.remember(frame_key,floating)
                if hint not in {'inventory','enhance'}:
                    reforge=try_reforge(image,self.ocr,td)
                    if reforge:return self.remember(frame_key,reforge)
                    if getattr(self,'catalog',None):
                        from character_reader import try_character
                        character=try_character(image,self.ocr,td,self.catalog)
                        if character:return self.remember(frame_key,character)
                if hint!='enhance':
                    inventory=try_inventory(image,self.ocr,td)
                    if inventory:return self.remember(frame_key,inventory)
            cards = find_cards(image) if mode=='auto' and image.width > 900 else []
            if mode=='batch' and image.width>900:
                located=locate_crafted_cards(image,self.ocr,td)
                if located:cards=located
            if mode == 'batch' or (mode == 'auto' and len(cards) >= 2):
                if not cards:
                    raise ValueError('未检测到制作总览装备卡片，请框选完整游戏窗口或读取全窗口截图。')
                return self.remember(frame_key,self.read_batch(image,cards,td,slot))
            # 全窗口强化页只读取左侧，避免货币/材料数量进入属性。
            if image.width > 900 and image.width / image.height > 1.2:
                cropped = image.crop((35,135,550,min(715,image.height)))
            else:
                cropped = image
            panel = Path(td)/'enhance-panel.png'
            cropped.save(panel)
            result = self.ocr.request(path=str(panel))
            gear = augment_names(parse_text(result['text']),result['text'])
            if image.width>900:
                detected=color_grade(image,(58,164,178,284))
                if detected:gear.grade=detected
            if image.width>900:
                for line in result.get('lines',[]):
                    words=[w for w in line.get('words',[]) if w['x']>=145]
                    if not words:continue
                    cy=sum(w['y']+w['h']/2 for w in words)/len(words)
                    name=_clean(''.join(w['text'] for w in sorted(words,key=lambda w:w['x'])))
                    if 95<cy<145 and len(name)>=3 and not any(x in name for x in ['传说','英雄','稀有','主属性','套装']):
                        gear.name=name;break
            # 提升后的14%(+7%)有时整段被原生OCR漏读。按属性标签定位数字行，
            # 去除橙色增量后用已校准的数字轮廓补读；不拿括号次数代替当前值。
            rows=[]
            for line in result.get('lines',[]):
                label = parse_stat(line.get('text','')+'999')
                if not label or not line.get('words'):
                    continue
                cy=sum(w['y']+w['h']/2 for w in line['words'])/len(line['words'])
                if any(abs(cy-r[0])<12 for r in rows):
                    continue
                region=cropped.crop((max(0,cropped.width-230),max(0,int(cy)-23),cropped.width-5,min(cropped.height,int(cy)+24)))
                value=template_number(region,self.templates['digits'])
                current=parse_stat(line.get('text',''))
                if value:
                    key=label.key.removesuffix('_pct') if label.key in {'atk_pct','hp_pct','def_pct'} else label.key
                    if key in {'atk','hp','def'} and value[1]:key+='_pct'
                    current=Stat(key,value[0])
                if current:
                    rows.append((cy,current))
            rows.sort(key=lambda r:r[0])
            if len(rows)>=3 and len(rows)-1>len(gear.subs):
                gear.main=rows[0][1]
                gear.subs=[r[1] for r in rows[1:]]
            expected=4 if gear.grade=='史诗' or (gear.enhance or 0)>=12 else 3
            if image.width>900 and len(gear.subs)<expected:
                body=cropped.crop((10,275,cropped.width-8,min(444,cropped.height)))
                enhanced=ImageOps.grayscale(body).point(lambda v:255 if v>78 else 0)
                bodyfile=Path(td)/'stat-body-contrast.png';enhanced.save(bodyfile)
                retry=self.ocr.request(path=str(bodyfile))
                candidates=[parse_stat(line) for line in retry.get('text','').splitlines()]
                candidates=[s for s in candidates if s]
                if len(candidates)==expected and len({s.key for s in candidates})==expected:
                    gear.subs=candidates
                    gear.warnings.append('灰色副词条经过二次增强识别，请核对。')
            if image.width > 900 and len(gear.subs)<expected:
                # Separate faint rows so a small speed digit is not omitted.
                parts=[]
                for index in range(expected):
                    centre=303+35.5*index
                    tile=cropped.crop((10,int(centre-17),cropped.width-8,int(centre+19)))
                    tile=ImageOps.grayscale(tile).point(lambda v:min(255,max(0,(v-30)*4)))
                    tile=tile.resize((tile.width*3,tile.height*3),Image.Resampling.LANCZOS)
                    parts.append(tile)
                montage=Image.new('L',(parts[0].width,180*len(parts)),0)
                for index,tile in enumerate(parts):montage.paste(tile,(0,index*180+25))
                rowfile=Path(td)/'isolated-stat-rows.png';montage.save(rowfile)
                isolated=self.ocr.request(path=str(rowfile))
                candidates=[parse_stat(line) for line in isolated.get('text','').splitlines()]
                candidates=[s for s in candidates if s]
                if len(candidates)==expected and len({s.key for s in candidates})==expected:
                    gear.subs=candidates
                    gear.warnings.append('副属性经过逐行放大识别，请核对。')
            precise=read_stat_rows(cropped,result,self.ocr,td,body=(180,465))
            if len(precise)>=len(gear.subs)+1:
                gear.main=precise[0];gear.subs=precise[1:5]
            if image.width > 900 and image.width / image.height > 1.2:
                anchored=header_metadata(result,cropped.width,cropped.height)
                meta=read_metadata(image,self.ocr,td,result['text'],known=anchored)
                for key in ('level','enhance'):
                    if anchored[key] is not None:meta[key]=anchored[key]
                gear.level=meta['level'] if meta['level'] is not None else gear.level;gear.enhance=meta['enhance'];gear.screen_score=meta['screen_score']
                gear.warnings.extend(meta['warnings'])
            else:
                gear.screen_score=official_score_lines(result['text'])
            preview=io.BytesIO();cropped.save(preview,format='PNG')
            return self.remember(frame_key,{'kind':'single','gear':gear,'text':result['text'],
                    'preview_png':base64.b64encode(preview.getvalue()).decode('ascii'),
                    'screen_score':gear.screen_score,
                    'source_note':'针对所提供的窗口布局校准；请人工校对等级、单位和强化角标。'})

    def read_batch(self,image,cards,directory,slot):
        numbers={}
        for row,box in enumerate(cards):
            for col in range(7):
                candidate=template_number(image.crop(field_box(*box[:2],col)),self.templates.get('digits',{}),yellow=col in {0,6})
                if candidate:
                    numbers[row,col]=candidate
        needed={(row,col) for row in range(len(cards)) for col in range(7) if (row,col) not in numbers}
        for position,value in read_number_tiles(image,cards,self.ocr,directory,needed).items():
            if position not in numbers:numbers[position]=value
        entries = []
        for index,box in enumerate(cards):
            x,y = box[:2]
            grade = grade_at(image,x,y)
            if not grade:grade=color_grade(image,(x,y,x+120,y+120))
            set_name,set_score = match_set_badge(image.crop((x+84,y+76,x+136,y+130)),threshold=.76)
            main_key,main_score = match_stat_icon(image,x+140,y+7,self.templates['stats'])
            level = numbers.get((index,0))
            if level and not 55 <= level[0] <= 99:
                level = None
            main = numbers.get((index,1))
            g = Gear(name=f'制作候选{index+1}',slot=slot,set_name=set_name or '',
                     grade=grade,level=int(level[0]) if level else None,enhance=0)
            if hasattr(cards,'levels'):g.level=cards.levels[index]
            warnings = ['制作总览按初始+0读取；只适用于新制作装备。']
            if main_key and main:
                if main_key in {'atk','hp','def'} and main[1]:
                    main_key += '_pct'
                g.main = Stat(main_key,main[0])
                # Unenhanced fixed left-side main stats identify these slots.
                # Right-side percentage mains continue to use the selected slot.
                fixed={('atk',100):'武器',('atk',103):'武器',('def',60):'铠甲',('hp',270):'头盔',('hp',276):'头盔'}
                inferred=fixed.get((main_key,main[0]))
                if inferred:g.slot=inferred
            for j,(dx,dy) in enumerate([(140,51),(246,51),(140,85),(246,85)]):
                icon,sim = match_stat_icon(image,x+dx,y+dy,self.templates['stats'])
                value = numbers.get((index,j+2))
                if icon and value:
                    if icon in {'atk','hp','def'} and value[1]:
                        icon += '_pct'
                    g.subs.append(Stat(icon,value[0]))
                elif icon or value:
                    warnings.append(f'副属性{j+1}图标或数字未确定，请补全。')
            if not set_name:
                warnings.append('套装图标未匹配，请手动选择。')
            g.warnings = warnings
            g.screen_score=numbers.get((index,6),(None,))[0]
            thumb=io.BytesIO();image.crop((x,y,x+350,y+140)).save(thumb,format='PNG')
            entries.append({'gear':g,'screen_score':numbers.get((index,6),(None,))[0],
                            'box':box,'set_similarity':round(set_score,3),'thumbnail_png':base64.b64encode(thumb.getvalue()).decode('ascii')})
        return {'kind':'batch','entries':entries,'text':'制作总览图标识别：逐件点击可校对。',
                'source_note':'黄色分数只作画面参考，不混入副属性参考分。未知图标会留空，不自动分解。'}
