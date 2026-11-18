"""Local JSON interface for future roster updates and user-authored hero panels."""
import json,math,uuid,shutil,re
from copy import deepcopy
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from hero_stats import ALL_BASE_DEFAULTS,STAT_NAMES
from core import ARCHETYPES

def validate_hero(record):
    result=deepcopy(record)
    if not str(result.get('name','')).strip():raise ValueError('角色名字不能为空')
    result['name']=str(result['name']).strip();result['name_en']=str(result.get('name_en') or result['name']).strip()
    result['id']=str(result.get('id') or 'custom_'+uuid.uuid4().hex[:12])
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',result['id']):raise ValueError('角色id只能含字母、数字、下划线、点或短横线')
    base=result.get('base',{});clean={}
    for key,label in STAT_NAMES.items():
        if key not in base:raise ValueError('缺少基础属性：'+label)
        try:value=float(str(base[key]).rstrip('%'))
        except (TypeError,ValueError):raise ValueError(label+'必须是数字')
        if not math.isfinite(value) or value<0 or (key in {'atk','hp','def','spd'} and value==0):raise ValueError(label+'数值无效')
        clean[key]=int(value) if value.is_integer() else value
    result['base']=clean;result['portrait']=str(result.get('portrait') or 'diche-icon.png')
    result['aliases']=[str(a).strip() for a in result.get('aliases',[]) if str(a).strip()]
    if result.get('archetype') not in ARCHETYPES:result['archetype']='攻击暴击输出'
    return result

def user_heroes(path):
    try:data=json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):return []
    records=data.get('heroes',[]) if isinstance(data,dict) else data
    return [validate_hero(h) for h in records] if isinstance(records,list) else []

def merge_catalog(catalog,records):
    output=deepcopy(catalog);byid={h['id']:h for h in output['heroes']}
    for record in records:byid[record['id']]=validate_hero(record)
    output['heroes']=sorted(byid.values(),key=lambda h:(h['name'],h['name_en']))
    return output

def save_user_heroes(path,records):
    path=Path(path);clean=[validate_hero(h) for h in records];path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():shutil.copy2(path,path.with_suffix('.previous.json'))
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps({'schema':1,'heroes':clean},ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)

def import_records(source,path,catalog):
    from local_json import read_json
    data=read_json(source);records=data.get('heroes',[]) if isinstance(data,dict) else data
    if not isinstance(records,list):raise ValueError('JSON应为角色数组，或包含heroes数组')
    # Validate the complete import before modifying any local record.
    known_names={h['name']:h['id'] for h in catalog['heroes']};known_names.update({h['name_en']:h['id'] for h in catalog['heroes']})
    clean=[]
    for record in records:
        record=deepcopy(record)
        if not record.get('id'):
            name=record.get('name_en') or record.get('name')
            if name in known_names:record['id']=known_names[name]
        clean.append(validate_hero(record))
    existing={h['id']:h for h in user_heroes(path)};existing.update({h['id']:h for h in clean});save_user_heroes(path,list(existing.values()))
    return len(clean)

class HeroEditor(tk.Toplevel):
    def __init__(self,parent,hero,on_save):
        super().__init__(parent);self.title('新增／编辑角色基础面板');self.geometry('480x660');self.configure(bg='#182438')
        self.hero=deepcopy(hero or {});self.callback=on_save;self.avatar=None
        self.name=tk.StringVar(value=self.hero.get('name',''));self.english=tk.StringVar(value=self.hero.get('name_en',''))
        self.aliases=tk.StringVar(value='，'.join(self.hero.get('aliases',[])));self.style=tk.StringVar(value=self.hero.get('archetype','攻击暴击输出'))
        self.element=tk.StringVar(value=self.hero.get('element',''));self.role=tk.StringVar(value=self.hero.get('role',''));self.stars=tk.StringVar(value=str(self.hero.get('stars','')))
        self.sets=tk.StringVar(value='，'.join(self.hero.get('sets',[])))
        frame=ttk.Frame(self,padding=14,style='Card.TFrame');frame.pack(fill='both',expand=True)
        for label,var in [('中文名字',self.name),('英文名（可选）',self.english),('外号（逗号分隔）',self.aliases)]:
            ttk.Label(frame,text=label).pack(anchor='w');ttk.Entry(frame,textvariable=var).pack(fill='x',pady=(2,7))
        ttk.Label(frame,text='候选用途类型').pack(anchor='w');ttk.Combobox(frame,textvariable=self.style,values=list(ARCHETYPES),state='readonly').pack(fill='x',pady=(2,7))
        from hero_picker import FILTER_GROUPS
        categories=ttk.Frame(frame,style='Card.TFrame');categories.pack(fill='x',pady=(0,7));self.category_maps={}
        for index,(label,key,options) in enumerate(FILTER_GROUPS):
            choices={title:value for value,title in options};var=tk.StringVar(value=next((title for title,value in choices.items() if str(self.hero.get(key,''))==value),'全部'))
            cell=ttk.Frame(categories,style='Card.TFrame');cell.pack(side='left',fill='x',expand=True,padx=(0,6))
            ttk.Label(cell,text=label).pack(anchor='w');ttk.Combobox(cell,textvariable=var,values=list(choices),state='readonly',width=10).pack(fill='x')
            self.category_maps[key]=(var,choices)
        ttk.Label(frame,text='适配套装（逗号分隔，可留空采用玩法模板）').pack(anchor='w');ttk.Entry(frame,textvariable=self.sets).pack(fill='x',pady=(2,7))
        grid=ttk.Frame(frame,style='Card.TFrame');grid.pack(fill='x');self.values={}
        for i,(key,label) in enumerate(STAT_NAMES.items()):
            var=tk.StringVar(value=str(self.hero.get('base',{}).get(key,ALL_BASE_DEFAULTS[key])));self.values[key]=var
            cell=ttk.Frame(grid,style='Card.TFrame');cell.grid(row=i//3,column=i%3,padx=(0,8),pady=4,sticky='ew');grid.columnconfigure(i%3,weight=1)
            ttk.Label(cell,text=label+('%' if key in {'crit','cdmg','eff','res','dual'} else '')).pack(anchor='w');ttk.Entry(cell,textvariable=var,width=11).pack(fill='x')
        row=ttk.Frame(frame,style='Card.TFrame');row.pack(fill='x',pady=12)
        ttk.Button(row,text='选择头像',command=self.choose_avatar).pack(side='left');ttk.Button(row,text='保存面板',command=self.save).pack(side='right')
        self.transient(parent);self.update_idletasks();x=max(0,min(parent.winfo_rootx()+parent.winfo_width()+8,self.winfo_screenwidth()-450));self.geometry(f'+{x}+{max(10,parent.winfo_rooty())}')
    def choose_avatar(self):
        self.avatar=filedialog.askopenfilename(parent=self,filetypes=[('头像','*.png *.jpg *.jpeg *.bmp')]) or None
    def save(self):
        record={**self.hero,'name':self.name.get(),'name_en':self.english.get(),'base':{k:v.get() for k,v in self.values.items()},'aliases':[a.strip() for a in self.aliases.get().replace('，',',').split(',') if a.strip()],'archetype':self.style.get()}
        for key,(var,choices) in self.category_maps.items():
            value=choices[var.get()];record[key]=int(value) if key=='stars' and value else value
        record['sets']=[s.strip() for s in self.sets.get().replace('，',',').split(',') if s.strip()]
        try:
            record=validate_hero(record);self.callback(record,self.avatar);self.destroy()
        except (ValueError,OSError) as exc:messagebox.showerror('未保存',str(exc),parent=self)
