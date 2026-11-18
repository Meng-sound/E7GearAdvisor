"""A spatially aligned crafted-equipment review board; never clicks the game."""
import base64,io,tkinter as tk
from tkinter import ttk
from PIL import Image,ImageTk
from core import LABELS,SLOTS
from picture_algorithm import breakdown
from advice import evaluate_advice
from quality_profiles import infer_quality

BG='#171b23';CARD='#202630';TEXT='#edf2fa';MUTED='#929db0';GREEN='#4b73ff';RED='#ff9b9b';GOLD='#f0cb89';FONT='Microsoft YaHei UI'
def crafted_decision(gear,base,score_mode='role',route=None):
    from picture_algorithm import ROUTES
    result=evaluate_advice(gear,base,route or ROUTES[0],score_mode=score_mode)
    expected={'史诗':4,'英雄':3,'稀有':2}.get(gear.grade)
    complete=bool(gear.subs) and len({s.key for s in gear.subs})==len(gear.subs) and (expected is None or len(gear.subs)==expected)
    unresolved=any('副属性' in w and ('未确认' in w or '未确定' in w) for w in gear.warnings)
    if gear.grade=='稀有':category='discard';title='分解'
    elif result.get('blocked_fixed_main'):category='discard';title='不推荐强化'
    elif not complete or unresolved:category='review';title='需复核'
    elif result['kind']=='enhance':category='keep';title='留着试强'
    elif result['kind'] in {'discard','backup'}:category='discard';title='分解候选'
    else:category='review';title='需复核'
    return {'category':category,'title':title,'score':result['score'],'gs':sum(x['score'] for x in breakdown(gear,score_mode='gs')),'reason':result['reasons'][-1] if result['reasons'] else '', 'advice':result}

from craft_board import CraftBoard as CraftWindow
