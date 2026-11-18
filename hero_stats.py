"""Full base-panel values; only atk/hp/def enter flat-substat conversion."""
ALL_BASE_DEFAULTS={'atk':1200,'hp':5000,'def':600,'spd':100,'crit':15,'cdmg':150,'eff':0,'res':0,'dual':3}
STAT_NAMES={'atk':'攻击力','hp':'生命值','def':'防御力','spd':'速度','crit':'暴击率','cdmg':'暴击伤害','eff':'效果命中','res':'效果抗性','dual':'夹攻率'}
PERCENT_STATS={'crit','cdmg','eff','res','dual'}
def stat_text(value,key):return f'{float(value):g}'+('%' if key in PERCENT_STATS else '')
