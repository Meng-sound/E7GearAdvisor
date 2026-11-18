"""Fribbels ItemDb WSS coefficients and Java Math.round, summed across six slots."""
import math
from core import SLOTS
COEFFICIENTS={'atk_pct':1,'hp_pct':1,'def_pct':1,'eff':1,'res':1,'spd':2,'crit':8/5,'cdmg':8/7,'atk':3.46/39,'hp':3.09/174,'def':4.99/31}

def raw_score(gear):
 total=0
 for stat in gear.subs:
  if stat.key not in COEFFICIENTS or isinstance(stat.value,bool) or not math.isfinite(stat.value) or stat.value<0:raise ValueError('GS 副属性数值无效')
  total+=stat.value*COEFFICIENTS[stat.key]
 return total

def item_score(gear):return math.floor(raw_score(gear)+.5)

def total_score(items):
 if set(items)!=set(SLOTS):raise ValueError('请先读取六个不同部位的装备')
 return sum(item_score(items[slot]) for slot in SLOTS)
