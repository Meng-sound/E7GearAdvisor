"""Read E7GW public server-rendered counters, without running site scripts.

This is a versioned HTML adapter, not a claimed public JSON API. Structural
changes raise an error rather than turning a failed parse into zero records.
"""
import datetime,re,time,urllib.parse,urllib.request,urllib.error
from html.parser import HTMLParser
from guild_war import team_key,count,NoRedirect
ORIGIN='https://e7gw.xyz'
class Node:
 def __init__(self,tag='',attrs=(),parent=None):self.tag=tag;self.attrs=dict(attrs);self.parent=parent;self.children=[]
 def all(self,tag=None):
  for child in self.children:
   if isinstance(child,Node):
    if tag is None or child.tag==tag:yield child
    yield from child.all(tag)
 def text(self):return ' '.join(' '.join(c.text() if isinstance(c,Node) else c for c in self.children).split())
class Document(HTMLParser):
 VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
 def __init__(self):super().__init__(convert_charrefs=True);self.root=Node();self.stack=[self.root];self.nodes=0
 def handle_starttag(self,tag,attrs):
  # HTML permits omitted </option>; E7GW's 393-name datalist uses this.
  # Match the browser's implied close rather than nesting every hero entry.
  if tag in ('option','optgroup'):
   for i in range(len(self.stack)-1,0,-1):
    if self.stack[i].tag in ('select','datalist'):break
    if self.stack[i].tag=='option':del self.stack[i:];break
  self.nodes+=1
  if self.nodes>150000 or len(self.stack)>150:raise ValueError('E7GW 页面结构过大')
  n=Node(tag,attrs,self.stack[-1]);self.stack[-1].children.append(n)
  if tag not in self.VOID:self.stack.append(n)
 def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs);self.handle_endtag(tag)
 def handle_endtag(self,tag):
  for i in range(len(self.stack)-1,0,-1):
   if self.stack[i].tag==tag:del self.stack[i:];break
 def handle_data(self,data):
  if self.stack[-1].tag not in ('script','style'):self.stack[-1].children.append(data)
def counters_url(defense,catalog):
 byid={h['id']:h['name_en'] for h in catalog['heroes']}
 names=sorted(byid[hid] for hid in team_key(defense))
 return ORIGIN+'/counters?'+urllib.parse.urlencode({'d'+str(i):name for i,name in enumerate(names,1)},quote_via=urllib.parse.quote)
def read_public_html(url):
 parsed=urllib.parse.urlsplit(url)
 if parsed.scheme!='https' or parsed.hostname!='e7gw.xyz' or parsed.path!='/counters':raise ValueError('不支持的 E7GW 查询地址')
 request=urllib.request.Request(url,headers={'Accept':'text/html','User-Agent':'E7GearAdvisor/1 public-statistics-reader'})
 for attempt in range(2):
  try:
   with urllib.request.build_opener(NoRedirect()).open(request,timeout=25) as response:
    raw=response.read(8*1024*1024+1)
    if len(raw)>8*1024*1024:raise ValueError('E7GW 响应超过8MB')
    content_type=response.headers.get_content_type()
    if content_type!='text/html':raise ValueError('E7GW 没有返回网页统计内容')
   break
  except (urllib.error.URLError,TimeoutError,ConnectionError) as error:
   temporary=(error.code in (429,500,502,503,504)) if isinstance(error,urllib.error.HTTPError) else isinstance(getattr(error,'reason',error),(TimeoutError,ConnectionError)) or 'timed out' in str(error).lower()
   if attempt or not temporary:raise
   time.sleep(.5)
 return raw.decode('utf8')
def _integer(text):
 if not re.fullmatch(r'\d[\d,]*',text.strip()):raise ValueError('E7GW 胜负字段格式已变化')
 return count(int(text.replace(',','')))
def parse_counters(html,defense,catalog):
 if not isinstance(html,str) or len(html.encode('utf8'))>8*1024*1024:raise ValueError('E7GW 页面无效或过大')
 doc=Document();doc.feed(html);root=doc.root
 lookup={h['name_en'].casefold():h['id'] for h in catalog['heroes']}
 def ids(names):return list(team_key([lookup[n.strip().casefold()] for n in names]))
 expected=team_key(defense)
 forms=list(root.all('form'));matched=False
 for form in forms:
  values={n.attrs.get('name'):n.attrs.get('value','') for n in form.all('input')}
  if all('d'+str(i) in values for i in (1,2,3)):
   try:matched=tuple(ids([values['d'+str(i)] for i in (1,2,3)]))==expected
   except (KeyError,ValueError):continue
   if matched:break
 if not matched:raise ValueError('E7GW 未返回所查询的三名防守英雄，可能被拦截或页面已变化')
 tables=[]
 for table in root.all('table'):
  heads=[n.text().upper() for n in table.all('th')]
  if {'OFFENSE TEAM','BATTLES','WINS','LOSSES'}.issubset(heads):tables.append((table,heads))
 rows=[];invalid=0
 for table,heads in tables:
  for tr in table.all('tr'):
   if 'data-filter-team' not in tr.attrs:continue
   try:
    team=ids(tr.attrs['data-filter-team'].split('|'));cells=[n for n in tr.children if isinstance(n,Node) and n.tag=='td']
    wins=_integer(cells[heads.index('WINS')].text());losses=_integer(cells[heads.index('LOSSES')].text());samples=_integer(cells[heads.index('BATTLES')].text())
    if wins+losses!=samples:raise ValueError('E7GW 总场次与胜负不符')
    rows.append({'heroes':team,'wins':wins,'losses':losses,'draws':0,'samples':samples})
   except (KeyError,ValueError,IndexError):invalid+=1
 text=root.text()
 no_data=bool(re.search(r'(?:no|0)\s+(?:data[- ]driven\s+)?(?:attack|offense)\s+teams|no\s+(?:data[- ]driven\s+)?(?:records|matchups|counters)|no solution data for that exact defense yet',text,re.I))
 if not tables and not no_data:raise ValueError('E7GW 战报表结构未识别，不能视作无战报')
 if invalid and not rows:raise ValueError('E7GW 战报行全部无法解析，请更新角色资料或适配器')
 cards=[]
 captured=re.search(r'report captured ([A-Za-z]{3} \d{1,2}, \d{4}) UTC',text)
 date=datetime.datetime.strptime(captured.group(1),'%b %d, %Y').date().isoformat() if captured else ''
 return {'schema':1,'defense':list(expected),'offenses':rows,'community_solutions':cards,'source':'E7GW · e7bot 公开统计','source_url':counters_url(expected,catalog),'last_match':date,'report_date':date,'date_kind':'统计快照',
  'complete':invalid==0,'invalid_rows':invalid,'raw_rows':len(rows)+invalid,'empty_reason':'网站暂无这组精确防守阵容的进攻样本，可切换其他数据源查询。' if not rows and no_data else '', 'fetched_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'adapter':'e7gw-html-v2'}
def fetch_e7gw(defense,catalog,reader=read_public_html):return parse_counters(reader(counters_url(defense,catalog)),defense,catalog)
