"""Position-bounded offline OCR observations for the supplied Chinese game UI."""
from dataclasses import dataclass,field
import hashlib
import re


def clean(text):return re.sub(r'\s+','',text).replace('觀','观').replace('覽','览')
def number(text):
    value=clean(text).replace(',','').replace('，','')
    return int(value) if re.fullmatch(r'\d{1,10}',value) else None


@dataclass
class Word:
    text:str
    x:float
    y:float
    w:float=.04
    h:float=.025
    confidence:float=1
    @property
    def point(self):return self.x+self.w/2,self.y+self.h/2


@dataclass
class Observation:
    scene:str='unknown'
    words:list=field(default_factory=list)
    buttons:dict=field(default_factory=dict)
    items:list=field(default_factory=list)
    gold:int|None=None
    sky:int|None=None
    price:int|None=None
    signature:str=''
    text:str=''
    reason:str=''


def in_box(word,box):
    x,y=word.point
    return box[0]<=x<=box[2] and box[1]<=y<=box[3]


def observe(words,mode):
    words=[w for w in words if w.confidence>=.78]
    text='\n'.join(w.text for w in words);compact=clean(text)
    result=Observation(words=words,text=text)
    def tokens(box):return [w for w in words if in_box(w,box)]
    def find(names,box=(0,0,1,1)):
        found=[w for w in tokens(box) if clean(w.text) in names]
        return max(found,key=lambda w:w.confidence).point if found else None
    def only_number(box):
        values=[number(w.text) for w in tokens(box) if number(w.text) is not None]
        return values[0] if len(values)==1 else None
    def button(key,names,box):
        point=find(names,box)
        if point:result.buttons[key]=point
    result.gold=only_number((.565,0,.68,.095))
    result.sky=only_number((.695,0,.765,.095))
    for names,reason in [(['行动力不足','行动力不够'],'体力不足'),(['背包已满','栏位不足','装备栏位已满'],'背包已满'),
                         (['战斗失败','挑战失败'],'战斗失败'),(['连接失败','网络连接','连接已中断'],'网络异常'),
                         (['充值','支付密码','购买天空石'],'出现充值界面')]:
        if any(name in compact for name in names):
            result.scene='blocked';result.reason=reason;return result
    center=''.join(clean(w.text) for w in tokens((.20,.22,.80,.85)))
    confirm=find({'确认','确定','购买'},(.35,.48,.80,.93))
    cancel=find({'取消'},(.15,.48,.62,.93))
    modal_numbers=[number(w.text) for w in tokens((.25,.25,.78,.90)) if number(w.text) is not None]
    if confirm and cancel:
        result.buttons['confirm']=confirm;result.buttons['cancel']=cancel
        if mode=='shop' and any(x in center for x in ('更新商品','刷新商品','更新商店','刷新商店','立即更新')) and 3 in modal_numbers:
            result.scene='refresh_confirm';result.price=3
        elif mode=='shop' and '购买' in center:
            result.scene='purchase_confirm'
            prices=[value for value in modal_numbers if value>=1000]
            result.price=prices[0] if len(prices)==1 else None
        elif mode=='theater' and any(x in center for x in ('观览券','观览劵','观看券','观览票','剧场门票')) and '购买' in center:
            result.scene='ticket_confirm'
            prices=[value for value in modal_numbers if value>=1000]
            result.price=prices[0] if len(prices)==1 else None
        elif mode=='theater' and any(x in center for x in ('使用剧场门票','使用观览券','使用观览票','使用剧场观览券')) and '购买' not in center:
            result.scene='use_ticket_confirm'
        elif mode in {'story','theater'} and any(x in center for x in ('跳过剧情','跳过故事','跳过此剧情')):
            result.scene='skip_confirm'
        else:result.scene='unknown_confirm';result.reason='弹窗用途未确认'
        result.signature=hashlib.sha256(center.encode()).hexdigest()[:16]
        return result
    if mode=='shop' and any('秘密商店' in clean(w.text) for w in tokens((0,0,.32,.14))):
        result.scene='shop'
        button('refresh',{'立即更新'},(0,.82,.35,1))
        for word in tokens((.80,.13,.99,.93)):
            if clean(word.text)!='购买':continue
            y=word.point[1]
            names=tokens((.52,y-.105,.81,y-.012))
            name=''.join(clean(w.text) for w in sorted(names,key=lambda w:(round(w.y/.025),w.x)))
            price=only_number((.84,y-.11,.99,y-.022))
            if not name or price is None:continue
            kind='covenant' if '誓约书签' in name else 'mystic' if any(s in name for s in ('神秘奖牌','神秘书签')) else 'gear' if price==1400000 else 'other'
            item=dict(name=name,price=price,kind=kind,point=word.point)
            levels=[w for w in tokens((.42,y-.13,.63,y)) if clean(w.text)=='85']
            if kind=='gear' and len(levels)==1:
                level=levels[0];item['inspect_point']=(level.point[0]+.013,level.point[1]+.020)
            result.items.append(item)
        # Vertical positions distinguish a changed scroll position even for identical names.
        key=[(item['name'],item['price'],round(item['point'][1],2)) for item in result.items]
        result.signature=hashlib.sha256(repr(key).encode()).hexdigest()[:16]
    elif mode=='theater':
        button('enter',{'入场'},(.72,.78,1,1))
        button('watch',{'进行观览','进行观看'},(.48,.78,.75,1))
        button('claim',{'领取观览奖励','领取观看奖励'},(.45,.68,.75,.9))
        button('next_episode',{'下一集','下一话','下一剧集'},(.45,.55,1,1))
        button('continue',{'点击继续','点击画面继续','继续'},(.25,.55,.95,1))
        locked=''.join(clean(w.text) for w in tokens((.71,.80,.88,1)))
        if re.search(r'\d+[天小时分]+后可观[看览]',locked):
            result.scene='locked';result.reason='所选剧集尚未开放'
        elif result.buttons.get('claim'):result.scene='theater_reward'
        elif result.buttons.get('next_episode'):result.scene='theater_end'
        elif result.buttons.get('continue') and any(word in compact for word in ('CLEAR','观览完成','观看完成','获得奖励')):result.scene='theater_clear'
        elif result.buttons.get('enter') and '月光剧场' in compact:result.scene='theater_home'
        elif result.buttons.get('watch'):result.scene='theater_episode'
    elif mode=='story':
        button('prepare',{'准备战斗'},(.72,.77,1,1))
        button('start',{'进行任务','战斗开始','开始战斗','出战'},(.68,.72,1,1))
        button('next',{'下一关','下一关卡','下一个关卡','下一区域'},(.55,.58,1,1))
        if result.buttons.get('prepare') and ('Episode' in text or '故事' in compact):result.scene='story_stage'
        elif result.buttons.get('start') and any(v in compact for v in ('选择队伍','战斗力','准备战斗','支援','队伍')):result.scene='story_team'
        elif result.buttons.get('next') and any(v in compact for v in ('胜利','通关','CLEAR','获得的道具','战斗结果')):result.scene='story_victory'
        elif any(in_box(w,(0,0,.30,.18)) and clean(w.text).upper()=='AUTO' for w in words):result.scene='battle'
    if mode in {'story','theater'} and result.scene=='unknown':
        button('skip',{'跳过','SKIP','Skip','略过'},(.70,0,1,.20))
        if result.buttons.get('skip'):result.scene='dialogue'
        elif any(clean(w.text) in {'自动','日志','对话记录','快进'} for w in tokens((0,.58,1,1))):
            # Require actual dialogue UI and a nontrivial subtitle, not arbitrary blank images.
            subtitle=''.join(w.text for w in tokens((.05,.65,.95,.97)))
            if len(re.findall(r'[\u4e00-\u9fff]',subtitle))>=12:
                result.scene='dialogue';result.buttons['advance']=(.50,.84)
    if not result.signature:
        result.signature=hashlib.sha256((result.scene+compact).encode()).hexdigest()[:16]
    return result


class GameOCR:
    def __init__(self):
        from local_ocr import LocalOCR
        self.local=LocalOCR()
    def read(self,image,mode):
        picture=image.convert('RGB')
        # The uploaded screenshots include a Windows title bar; native capture does not.
        if 1.70<picture.width/picture.height<1.75:
            strip=picture.crop((0,0,picture.width,15)).resize((64,1))
            if sum(min(pixel)>190 for pixel in strip.getdata())>45:
                picture=picture.crop((0,picture.height-round(picture.width*9/16),picture.width,picture.height))
        if picture.width>1600:picture=picture.resize((1600,round(picture.height*1600/picture.width)))
        values,_=self.local.engine(picture,use_cls=False)
        words=[]
        for box,text,confidence in values or []:
            xs=[point[0] for point in box];ys=[point[1] for point in box]
            words.append(Word(text,min(xs)/picture.width,min(ys)/picture.height,
                              (max(xs)-min(xs))/picture.width,(max(ys)-min(ys))/picture.height,float(confidence)))
        result=observe(words,mode)
        if mode in {'shop','theater'}:
            for key,box in (('gold',(.565,0,.68,.095)),('sky',(.695,0,.765,.095))):
                if getattr(result,key) is not None:continue
                crop=picture.crop(tuple(round(value*(picture.width if i%2==0 else picture.height)) for i,value in enumerate(box)))
                crop=crop.resize((crop.width*3,crop.height*3))
                values,_=self.local.engine(crop,use_cls=False)
                candidates=[]
                for _,text,confidence in values or []:
                    if confidence<.8:continue
                    tokens=re.findall(r'(?<!\d)\d[\d,，]*(?!\d)',text)
                    candidates.extend(number(token) for token in tokens if number(token) is not None)
                large=[value for value in candidates if value>=1000]
                if len(large)==1:setattr(result,key,large[0])
                elif len(candidates)==1:setattr(result,key,candidates[0])
        return result
    def close(self):self.local.close()
