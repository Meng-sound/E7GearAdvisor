"""Explain unqueried defenses and empty result sets without inventing records."""
def defense_issue(ids,names=None):
 names=names or {};filled=[h for h in ids if h]
 duplicates=sorted({h for h in filled if filled.count(h)>1})
 if duplicates:return '防守英雄重复：'+'、'.join(names.get(h,h) for h in duplicates)+'。每场需要三名不同英雄。'
 if len(filled)<3:return f'还缺 {3-len(filled)} 名防守英雄。请点击空位补齐后查询。'
 return ''
def empty_feedback(record,minimum,include=(),exclude=(),partner=()):
 rows=record.get('offenses',[])
 if not rows:
  if record.get('invalid_rows'):return '接口返回的战报未能解析，请更新英雄资料或数据适配器。'
  return '查询成功，当前来源本次返回 0 组进攻战报。\n可能尚未收录这队，不能据此判断其他来源也没有。\n可切换来源；更多菜单提供百里 E7BOT 网页查询（需登录）。'
 reasons=[]
 if not any(r['samples']>=minimum for r in rows):reasons.append(f'最少样本 {minimum} 过高')
 if include:reasons.append(f'包含英雄条件选了{len(include)}人，而每队只有3人，无法同时满足' if len(include)>3 else '包含英雄条件（需同时出现）')
 if exclude:reasons.append('排除英雄条件')
 if partner:reasons.append('另一场已选进攻英雄的去重条件')
 return f'来源已返回 {len(rows)} 组战报，当前筛选后没有可显示阵容。\n检查：'+('、'.join(reasons) if reasons else '最少样本和筛选条件')+'。可清除筛选后重试。'
