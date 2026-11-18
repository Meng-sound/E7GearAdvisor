"""Editable per-substat formulas evaluated by a bounded arithmetic interpreter."""
import ast,copy,json,math,operator
from functools import lru_cache
from pathlib import Path
from core import LABELS

DEFAULT_FORMULAS={key:('value / base * 100' if key in ('atk','hp','def') else 'value * 1.6' if key=='crit' else 'value * 8 / 7' if key=='cdmg' else 'value * 2' if key=='spd' else 'value') for key in LABELS}
DEFAULT={'schema':1,'enabled':False,'name':'自定义算法','formulas':DEFAULT_FORMULAS}
_settings=copy.deepcopy(DEFAULT)
VARIABLES={'value','base','level','enhance','base_atk','base_hp','base_def','base_spd'}
OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.Pow:operator.pow}
FUNCS={'min':min,'max':max,'abs':abs,'round':round}

@lru_cache(maxsize=256)
def parse(expression):
 if not isinstance(expression,str) or not expression.strip() or len(expression)>256:raise ValueError('算式需要1至256个字符')
 try:tree=ast.parse(expression,mode='eval')
 except SyntaxError:raise ValueError('算式语法错误，请使用 value、base 和四则运算') from None
 if len(list(ast.walk(tree)))>100:raise ValueError('算式过于复杂')
 def check(node):
  if isinstance(node,ast.Expression):check(node.body)
  elif isinstance(node,ast.Constant):
   if isinstance(node.value,bool) or not isinstance(node.value,(int,float)) or not math.isfinite(node.value) or abs(node.value)>1e6:raise ValueError('算式常数无效或过大')
  elif isinstance(node,ast.Name):
   if node.id not in VARIABLES:raise ValueError('不支持的变量：'+node.id)
  elif isinstance(node,ast.BinOp) and type(node.op) in OPS:
   if isinstance(node.op,ast.Pow) and (not isinstance(node.right,ast.Constant) or not isinstance(node.right.value,int) or not 0<=node.right.value<=6):raise ValueError('幂指数只支持0至6的整数常量')
   check(node.left);check(node.right)
  elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):check(node.operand)
  elif isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in FUNCS and not node.keywords and 1<=len(node.args)<=5:
   for arg in node.args:check(arg)
  else:raise ValueError('只支持算术、min/max/abs/round；不允许执行Python代码')
 check(tree);return tree.body

def evaluate(expression,variables):
 if not isinstance(expression,str):raise ValueError('公式必须是文本')
 def bounded(value):
  if not isinstance(value,(int,float)) or not math.isfinite(value) or abs(value)>1e12:raise ValueError('公式中间结果超过允许范围')
  return value
 def run(node):
  if isinstance(node,ast.Constant):return node.value
  if isinstance(node,ast.Name):return variables[node.id]
  if isinstance(node,ast.UnaryOp):return -run(node.operand) if isinstance(node.op,ast.USub) else run(node.operand)
  if isinstance(node,ast.BinOp):return bounded(OPS[type(node.op)](run(node.left),run(node.right)))
  return bounded(FUNCS[node.func.id](*(run(a) for a in node.args)))
 try:value=run(parse(expression))
 except (ZeroDivisionError,OverflowError,ValueError,TypeError) as e:raise ValueError('算式无法计算：'+str(e)) from None
 if not isinstance(value,(int,float)) or not math.isfinite(value) or abs(value)>1e6:raise ValueError('算分结果超出允许范围')
 return float(value)

def current():return copy.deepcopy(_settings)
def enabled():return _settings['enabled']
def validate(data):
 if not isinstance(data,dict) or data.get('schema',1)!=1 or not isinstance(data.get('enabled',False),bool):raise ValueError('自定义算分配置格式错误')
 name=data.get('name','自定义算法')
 if not isinstance(name,str) or not 1<=len(name.strip())<=24:raise ValueError('算法名称需要1至24个字')
 formulas=data.get('formulas',{})
 if not isinstance(formulas,dict) or set(formulas)-set(LABELS):raise ValueError('词条算式字段无效')
 result={**copy.deepcopy(DEFAULT),'enabled':data.get('enabled',False),'name':name.strip(),'formulas':{**DEFAULT_FORMULAS,**formulas}}
 for key,expression in result['formulas'].items():
  for value in (1,10,100):
   try:evaluate(expression,{'value':value,'base':1000,'level':85,'enhance':15,'base_atk':1000,'base_hp':6000,'base_def':600,'base_spd':100})
   except ValueError as e:raise ValueError(LABELS[key]+'：'+str(e)) from None
 return result
def configure(path):
 global _settings
 _settings=copy.deepcopy(DEFAULT)
 if Path(path).exists():_settings=validate(json.loads(Path(path).read_text(encoding='utf8')))
def save(path,data):
 global _settings
 clean=validate(data);path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(clean,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(path);_settings=clean
def score_stat(stat,base=None,gear=None,profile=None):
 profile=profile or _settings;base=base or {};reference={key:float(base.get(key,default)) for key,default in {'atk':1359,'hp':5542,'def':585,'spd':105}.items()}
 if any(not math.isfinite(v) or v<=0 for v in reference.values()):raise ValueError('角色基础面板必须大于0且为有限数值')
 variables={'value':stat.value,'base':reference[stat.key] if stat.key in ('atk','hp','def') else 1,'level':getattr(gear,'level',None) or 0,'enhance':getattr(gear,'enhance',None) or 0,**{'base_'+k:v for k,v in reference.items()}}
 return evaluate(profile['formulas'][stat.key],variables)
def breakdown(gear,base):
 return [{'key':stat.key,'value':stat.value,'score':score_stat(stat,base,gear),'formula':f"{_settings['name']}：{_settings['formulas'][stat.key]}（value={stat.value:g}）"} for stat in gear.subs]
