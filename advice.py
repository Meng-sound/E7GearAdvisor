"""Conditional suggestions when metadata is missing; never invent OCR readouts."""
from copy import deepcopy
import math
from core import SLOTS
from threshold_settings import current
from picture_algorithm import evaluate_picture,breakdown,ROUTES

def evaluate_advice(gear,base=None,route=ROUTES[0],reforged=False,fixed_main_confirmed=False,score_mode='role'):
    if any(not math.isfinite(s.value) or s.value<=0 for s in gear.subs):raise ValueError('副属性必须是大于0的有效数值')
    parts=breakdown(gear,base,score_mode)
    score=sum(x['score'] for x in parts)
    common={'score':score,'breakdown':parts,'speed':next((s.value for s in gear.subs if s.key=='spd'),0),'errors':[],'route':'参考','next_stage':None,'conditional':False}
    if gear.grade=='稀有':return {**common,'kind':'discard','title':'蓝色装备：建议分解','reasons':['按当前规则，蓝色装备一律分解，不触发分数或速度保留特例。'],'threshold_text':'蓝色装备：直接分解'}
    if not parts:return {**common,'kind':'waiting','title':'等待读取副属性','reasons':['读取装备后显示得分和建议。']}
    grades=[gear.grade] if gear.grade in {'史诗','英雄'} else ['英雄','史诗']
    stages=[gear.enhance] if gear.enhance is not None and 0<=gear.enhance<=15 else ([15] if gear.level==90 else [0,6,9,12,15])
    slots=[gear.slot] if gear.slot in SLOTS else ['武器','戒指']
    levels=[gear.level] if gear.level is not None else ([85,88,90] if stages==[15] else [85,88])
    cases=[]
    for grade in grades:
      for stage in stages:
       for slot in slots:
        for level in levels:
         g=deepcopy(gear);g.grade=grade;g.enhance=stage;g.slot=slot;g.level=level
         # Main and set do not enter substat scoring. Missing fields stay blank in UI.
         r=evaluate_picture(g,base,route,reforged or level==90,fixed_main_confirmed,score_mode=score_mode,advisory=True)
         if r['kind']=='review':continue
         tags=[]
         if len(stages)>1:tags.append(f'+{stage}')
         if len(grades)>1 and stage<6:tags.append('紫装' if grade=='英雄' else '红装')
         if len(slots)>1:tags.append('左三件' if slot=='武器' else '右三件')
         if len(levels)>1:tags.append(f'{level}级')
         cases.append(('／'.join(tags),r))
    if not cases:return {**common,'kind':'backup','title':'暂不追加投入','reasons':['当前得分已计算；这个属性组合不在流程图的完整分支内。']}
    case_details=[]
    for label,r in cases:
        gate=r.get('threshold');text=f'{label}：{r["title"]}'+(f'（门槛{gate}分）' if gate is not None else '')
        if text not in case_details:case_details.append(text)
    keys={(r['kind'],r.get('next_stage')) for _,r in cases}
    if len(keys)==1:
        result=cases[0][1]
        expected=2+int((gear.enhance or 0)>=9)+int((gear.enhance or 0)>=12) if gear.grade=='稀有' else 3 if gear.grade=='英雄' and (gear.enhance or 0)<12 else 4
        if len(gear.subs)<expected:
            result['reasons'].append(f'当前按已读{len(gear.subs)}条副属性计算。')
            if result['kind']=='discard' and not result.get('blocked_fixed_main'):result.update(kind='backup',title='暂不追加投入')
    else:
        lines=[]
        for label,r in cases:
            gate=r.get('threshold');text=f'{label}：{r["title"]}'+(f'（门槛{gate}分）' if gate is not None else '')
            if text not in lines:lines.append(text)
        result={**common,'kind':'conditional','title':'按已读属性给出条件建议','conditional':True,'reasons':lines,'cases':lines}
    # User's initial-item retention exception is independent of score thresholds.
    if (gear.enhance==0 and gear.grade in {'英雄','史诗'} and common['speed']>0
        and (gear.grade=='史诗' or common['speed']>=3) and not result.get('blocked_fixed_main')):
        reason=('未强化红装有速度词条' if gear.grade=='史诗' else '未强化紫装速度≥3')+'，按自定保留规则留着试强。'
        if result['kind']!='enhance':result.update(kind='enhance',title='按速度保留，试强到 +6',next_stage=6,route='初始速度保留')
        result['speed_retention']=True
        result['reasons'].append(reason)
    if score_mode=='gs':
        result['reasons']=['Fribbels GS 使用独立门槛比较原始分，请按需求校准保留标准。',*[line.replace('民间分','标准GS') for line in result['reasons']]]
    thresholds=sorted({r['threshold'] for _,r in cases if r.get('threshold') is not None})
    side='右三件' if gear.slot in SLOTS[3:] else '左三件' if gear.slot in SLOTS[:3] else '部位未识别'
    if result.get('blocked_fixed_main'):
        result['threshold_text']='右三件 · 固定主属性\n不推荐强化'
    elif result.get('threshold') is not None:
        gate=result['threshold'];gap=max(0,gate-score)
        grade_text={'英雄':'紫装','史诗':'红装'}.get(gear.grade,'品质未识别') if (gear.enhance or 0)<6 else f'+{gear.enhance}'
        result['threshold_text']=f'{side} · {grade_text}\n门槛 {gate:g}分'
        if result.get('speed_threshold') is not None:result['threshold_text']+=f" / 追速{result['speed_threshold']:g}速"
        else:result['threshold_text']+=f' · 差 {gap:.2f}分' if gap>1e-9 else ' · 已达标'
    elif thresholds:result['threshold_text']='可能门槛 '+ ' / '.join(f'{n:g}' for n in thresholds)+'分（强化阶段未读全）'
    else:
        v=current(score_mode)['speed'];key='90' if gear.level==90 else '15' if (gear.enhance or 0)>=15 else '12' if (gear.enhance or 0)>=12 else 'entry' if (gear.enhance or 0)<6 else '6'
        result['threshold_text']=f'速度门槛 {v[key]:g}（追速分支）'
    if len(slots)>1 and len(stages)==1:
        groups={}
        for label,r in cases:
            if r.get('threshold') is not None:groups.setdefault('右三件' if '右三件' in label else '左三件',set()).add(r['threshold'])
        if groups:result['threshold_text']='；'.join(k+'门槛'+'/'.join(f'{n:g}' for n in sorted(v))+'分' for k,v in groups.items())
    if len(grades)>1 and len(stages)==1 and stages[0]<6:
        c=current(score_mode);labels={k:f'紫{c[k]["purple"]:g}／红{c[k]["red"]:g}分' for k in ('left','right')}
        result['threshold_text']=('左三件 '+labels['left']+'\n右三件 '+labels['right'] if len(slots)>1 else side+' · 品质未识别\n'+labels['right' if gear.slot in SLOTS[3:] else 'left'])
    if gear.slot in SLOTS[3:] and gear.main is None:
        result.update(kind='conditional',title='主属性待校验',conditional=True)
        result['reasons'].insert(0,'右三件主属性未识别：若为固定攻击、防御或生命，不推荐强化；其余主属性按所示门槛判断。')
    if len(stages)>1 or len(slots)>1 or len(levels)>1 or len(grades)>1:result['case_details']=case_details
    return result
