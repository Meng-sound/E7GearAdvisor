"""Historical official probabilities, baseline 2022-05-25; conditional on stat hit."""
import json
from pathlib import Path

DATA=json.loads((Path(__file__).parent/'data/official-rolls.json').read_text(encoding='utf-8'))
PROFILES=['自动（88级需选来源）','真88级表','全部按72–85表','仅速度按72–85表','特殊58–71表','不核对概率']

def distribution(level,grade,key,profile=PROFILES[0]):
    if profile==PROFILES[-1] or level==90:return None
    if profile==PROFILES[4]:tier='58_71'
    elif profile==PROFILES[2]:tier='72_85'
    elif level==88:
        if profile==PROFILES[1]:tier='88'
        elif profile==PROFILES[3]:tier='72_85' if key=='spd' else '88'
        else:return None
    elif level is not None and 72<=level<=85:tier='72_85'
    elif level is not None and 58<=level<=71:tier='58_71'
    else:return None
    return DATA['tiers'][tier].get(key,{}).get({'史诗':'epic','英雄':'heroic','稀有':'rare'}.get(grade,''))

def describe_roll(level,grade,key,delta,profile=PROFILES[0]):
    values=distribution(level,grade,key,profile)
    if not values:return '无适用概率表：88级请选择来源；90级重铸增量不套强化表。'
    total=sum(p for v,p in values);mean=sum(v*p for v,p in values)/total
    lo=min(v for v,p in values);hi=max(v for v,p in values)
    prob=sum(p for v,p in values if abs(v-delta)<1e-8)
    rank='满跳' if delta==hi else '高于均值' if delta>mean else '低于均值' if delta<mean else '等于均值'
    return f'该词条单跳范围{lo}–{hi}，均值{mean:.3f}；'+(f'本次{rank}，命中此词条后出现该数值的条件概率约{prob:g}%。' if prob else '本次不在单跳表内，请核对是否跨节点／洗词条。')+'（公告基准2022-05-25）'

def next_roll_note(gear,profile=PROFILES[0]):
    if gear.level==90 or gear.enhance==15:return '已成品；不预测普通强化跳值。'
    target=(gear.enhance//3+1)*3
    if gear.grade=='英雄' and target==12:return '下一节点+12新增第4条，不是给现有词条随机强化。'
    return f'下一副属性节点+{target}：现有{len(gear.subs)}条等概率选一条，各约{100/len(gear.subs):.2f}%；下面的数值概率以已命中对应词条为条件。'
