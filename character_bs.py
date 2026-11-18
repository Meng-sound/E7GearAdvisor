"""Fribbels Hero Library BS, ported from e7/heroBuilds.js.

Inputs use in-game percentage points, not fractional base percentages.
Artifact attack/HP are actual additive stats. Unknown passive/imprint bonuses
must be removed by the user's final-stat corrections; no guessed +30 artifact.
"""
import math
KEYS=('atk','def','hp','spd','crit','cdmg','eff','res')
SET_SIZE={'攻击':4,'生命':2,'防御':2,'速度':4,'暴击':2,'暴伤':4,'命中':2,'抵抗':2,'反击':4,'吸血':4,'免疫':2,'愤怒':4,'复仇':4,'伤口':4,'贯穿':2,'夹攻':2,'激流':2,'逆袭':4,'追击':2,'保护':4,'回击':4}
SET_ALIASES={'破灭':'暴伤','爆伤':'暴伤','效果命中':'命中','效果抵抗':'抵抗','协击':'夹攻','set_att':'攻击','set_max_hp':'生命','set_def':'防御','set_speed':'速度','set_cri':'暴击','set_cri_dmg':'暴伤','set_acc':'命中','set_res':'抵抗','set_torrent':'激流','set_revenge':'复仇','set_revenant':'逆袭'}
def _number(value,name,positive=False):
 if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or abs(value)>1e8 or (positive and value<=0):raise ValueError(name+'必须为有效数值'+('且大于0' if positive else ''))
 return float(value)
def calculate_bs(panel,base,sets=(),artifact=None,corrections=None):
 if any(k not in panel or k not in base for k in KEYS):raise ValueError('角色面板与基础值需要八项完整属性')
 p={k:_number(panel[k],k) for k in KEYS};b={k:_number(base[k],'基础'+k,k in ('atk','def','hp','spd')) for k in KEYS}
 if any(v<0 for v in p.values()):raise ValueError('角色面板不能为负数')
 artifact=artifact or {};corrections=corrections or {}
 if set(artifact)-{'atk','hp'} or set(corrections)-set(KEYS):raise ValueError('加成校正字段无效')
 a={k:_number(artifact.get(k,0),'神器'+k) for k in ('atk','hp')}
 if min(a.values())<0:raise ValueError('神器数值不能为负')
 p={k:p[k]-_number(corrections.get(k,0),'额外加成'+k) for k in KEYS}
 names=[SET_ALIASES.get(s,s) for s in sets if s and s!='无']
 if any(s not in SET_SIZE for s in names):raise ValueError('未知套装，请手动校正加成')
 if sum(SET_SIZE[s] for s in names)>6:raise ValueError('已激活套装不能超过六件装备')
 n={s:names.count(s) for s in SET_SIZE}
 parts={
  'hp':(p['hp']-b['hp']-a['hp'])/b['hp']*100-n['生命']*20+n['激流']*10,
  'atk':(p['atk']-b['atk']-a['atk'])/b['atk']*100-n['攻击']*45,
  'def':(p['def']-b['def'])/b['def']*100-n['防御']*20,
  'spd':p['spd']-b['spd']-n['速度']*math.floor(.25*b['spd'])-n['复仇']*math.floor(.12*b['spd'])-n['逆袭']*math.floor(.15*b['spd']),
  'crit':min(100,p['crit'])-b['crit']-n['暴击']*12,
  'cdmg':min(350,p['cdmg'])-b['cdmg']-n['暴伤']*60,
  'eff':p['eff']-b['eff']-n['命中']*20,
  'res':p['res']-b['res']-n['抵抗']*20,
 }
 bad=[k for k,v in parts.items() if v < -1]
 if bad:raise ValueError('扣除后属性为负，请核对基础、套装、神器及额外加成：'+', '.join(bad))
 weights={'crit':1.6,'cdmg':1.14,'spd':2}
 score=sum(v*weights.get(k,1) for k,v in parts.items())
 return {'bs':math.floor(score),'raw_score':score,'parts':parts,'contributions':{k:v*weights.get(k,1) for k,v in parts.items()},'sets':names,'algorithm':'Fribbels Hero Library BS'}
