"""User's 2026-11-15 flowchart and civilian-score image; no upstream gates."""
import math
from threshold_settings import current as threshold_config
from core import LABELS, validate

DEFAULT_BASE={'atk':1200,'hp':5000,'def':600}
WEIGHTS={k:(8/5 if k=='crit' else 8/7 if k=='cdmg' else 2 if k=='spd' else 1) for k in LABELS}
ROUTES=['自动（总分优先，低分追速）','仅总分路线','追速路线']

def breakdown(gear,base=None,score_mode='role'):
    if score_mode not in ('gs','role','custom'):raise ValueError('未知算分算法')
    if score_mode=='gs':
        from fribbels_gs import COEFFICIENTS
        coefficients=COEFFICIENTS
        return [{'key':s.key,'value':s.value,'score':s.value*coefficients[s.key],
                 'formula':f'{s.value:g} × {coefficients[s.key]:.6g}'} for s in gear.subs]
    full_base=base or {}
    base={key:full_base.get(key,value) for key,value in DEFAULT_BASE.items()}
    if any(not math.isfinite(float(v)) or float(v)<=0 for v in base.values()):
        raise ValueError('角色基础攻击、生命、防御必须是大于0的有限数值')
    import scoring_settings
    if score_mode=='custom':return scoring_settings.breakdown(gear,{**full_base,**base})
    return [{'key':s.key,'value':s.value,'score':s.value/float(base[s.key])*100 if s.key in base else s.value*WEIGHTS[s.key],
             'formula':f'{s.value:g} ÷ {float(base[s.key]):g} × 100' if s.key in base else f'{s.value:g} × {WEIGHTS[s.key]:g}'} for s in gear.subs]

def evaluate_picture(gear,base=None,route=ROUTES[0],reforged=False,fixed_main_confirmed=False,score_mode='role',advisory=False):
    errors=[] if advisory else validate(gear)
    if not advisory and gear.grade not in {'史诗','英雄'}:errors.append('此流程图只覆盖红装和紫装，其他品质需自行判断')
    valid_subs=all(s.key in LABELS and math.isfinite(s.value) and s.value>0 for s in gear.subs)
    details=breakdown(gear,base,score_mode) if valid_subs else []
    score=sum(x['score'] for x in details);speed=next((s.value for s in gear.subs if s.key=='spd'),0)
    right=gear.slot in {'项链','戒指','鞋子'}
    result={'kind':'review','title':'需校验，人工判断','errors':errors,'reasons':list(errors),'score':score,'breakdown':details,'speed':speed,'route':'总分','next_stage':None}
    def finish(kind,title,reason,target=None):
        result.update(kind=kind,title=title,next_stage=target)
        if result.get('route')=='追速':
            reason=f"左三件当前{score:.3f}分、速度{speed:g}；分数门槛{result.get('threshold','—')}，追速门槛{result.get('speed_threshold','—')}。"
            if kind in ('usable','backup') and gear.enhance==12:reason+=f"追速能用分门槛{threshold_config(score_mode)['speed']['usable_score']:g}。"
        result['reasons'].append(reason);return result
    if right and gear.main and gear.main.key in {'atk','hp','def'}:
        result['blocked_fixed_main']=True
        return finish('discard','不推荐强化','右三件主属性为固定攻击、防御或生命，按流程图不推荐强化；分数和速度均不放行。')
    if errors:return result
    if gear.enhance not in {0,3,6,9,12,15}:
        return finish('review','请到副属性节点再判断','流程图节点为未强化、+6、+9、+12、+15。')
    e=gear.enhance;recast=reforged or gear.level==90;cfg=threshold_config(score_mode);side_cfg=cfg['right' if right else 'left'];speed_cfg=cfg['speed']
    if recast and e!=15:return finish('review','请核对重铸状态','重铸后规则只适用+15成品。')
    entry=side_cfg['red' if gear.grade=='史诗' else 'purple']
    threshold=side_cfg['90'] if recast else entry if e<6 else side_cfg[str(e)]
    result['threshold']=threshold
    speed_route=not right and (route==ROUTES[2] or (route==ROUTES[0] and score+1e-9<threshold and (e<12 or speed>=speed_cfg['6'])))
    if speed_route:
        result['route']='追速'
        if recast:
            result['speed_threshold']=speed_cfg['90']
            return finish('excellent' if speed>=speed_cfg['90'] else 'usable','重点保留，传家宝' if speed>=speed_cfg['90'] else '成品能用',f'重铸后速度{speed:g}，流程图优秀线20速。')
        if e<6:
            result['speed_threshold']=speed_cfg['entry']
            return finish('enhance','建议强化到 +6','左三件分数未达入场门槛，但初始速度达到4，按追速路线试强到+6。',6) if speed>=speed_cfg['entry'] else finish('discard','分解／出售候选',f'左三件分数未达{entry}分，初始速度也未达到4。')
        if e<12:
            result['speed_threshold']=speed_cfg['6']
            return finish('enhance','继续追速到 +12','速度达到10，走追速路线到+12；按实际读取的速度判断。',12) if speed>=speed_cfg['6'] else finish('discard','分解／出售候选','分数未达当前门槛，追速也未达到10速。')
        if e==12:
            result['speed_threshold']=speed_cfg['12' if e==12 else '15']
            if speed>=speed_cfg['12'] or score+1e-9>=cfg['left']['12']:return finish('enhance','建议强化到 +15','左三件速度达到15，或者总分达到46。',15)
            return finish('usable','停止投入，作为成品使用','未达15速，总分达到40但不足46。') if score+1e-9>=speed_cfg['usable_score'] else finish('backup','停止投入，留作替补','未达15速，而且总分也不足40。')
        result['speed_threshold']=speed_cfg['12' if e==12 else '15']
        if speed>=speed_cfg['15'] and gear.level!=85:return finish('usable','保留使用','+15达到15速；当前不是85级，不套用85→90重铸规则。')
        return finish('reforge','保留，可考虑重铸','+15速度达到15。') if speed>=speed_cfg['15'] else finish('usable','停止投入，成品能用','+15速度不足15，追速路线不建议重铸。')
    side='右三件' if right else '左三件'
    reason=f'{side}当前{score:.3f}分，门槛{threshold}分，不叠加强化等级分。'
    if recast:return finish('excellent' if score+1e-9>=threshold else 'usable','重点保留，传家宝' if score+1e-9>=threshold else '成品能用',reason)
    target=6 if e<6 else 9 if e==6 else 12 if e==9 else 15 if e==12 else None
    if score+1e-9>=threshold:
        if target:return finish('enhance',f'建议强化到 +{target}',reason,target)
        if gear.level!=85:return finish('usable','保留使用',reason+'当前不是85级，不套用85→90重铸规则。')
        return finish('reforge','保留，可考虑重铸',reason)
    fail='discard' if e<12 else 'backup' if e==12 or not right else 'usable'
    return finish(fail,{'discard':'分解／出售候选','backup':'停止投入，留作替补','usable':'停止投入，成品能用'}[fail],reason)
