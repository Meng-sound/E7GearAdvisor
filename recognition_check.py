"""Completeness notice, independent of advice; official score is optional."""
from core import SLOTS
def recognition_notice(gear):
    missing=[]
    if gear.level is None:missing.append('装备等级')
    if gear.enhance is None:missing.append('强化等级')
    if gear.slot not in SLOTS:missing.append('装备部位')
    if not gear.grade:missing.append('品质')
    if not gear.set_name:missing.append('套装')
    if gear.main is None:missing.append('主属性')
    expected=2+int((gear.enhance or 0)>=9)+int((gear.enhance or 0)>=12) if gear.grade=='稀有' else 3 if gear.grade=='英雄' and gear.enhance is not None and gear.enhance<12 else 4
    if len(gear.subs)<expected:missing.append('副属性未读全')
    return '需人工校验：'+'、'.join(missing)+'。' if missing else ''
