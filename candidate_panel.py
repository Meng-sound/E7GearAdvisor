"""Docked hero candidates with local portraits and Chinese names."""
import re
import copy,webbrowser
from urllib.parse import quote_plus
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from PIL import Image,ImageTk
from core import recommend,ARCHETYPES,DEFAULT_RULES
from picture_algorithm import breakdown,WEIGHTS
from build_reference import enrich_profiles
from set_icons import canonical,display as display_set

def fold(text):return ''.join(c for c in text.casefold() if c.isalnum())

# Local playstyle references, not statistics downloaded from Fribbels.
STYLE_SETS={
 '攻击暴击输出':['速度','攻击','破灭','暴击','贯穿','愤怒'],
 '生命暴击输出':['速度','反击','吸血','伤口','贯穿','免疫','暴击'],
 '防御暴击输出':['速度','反击','吸血','防御','贯穿','免疫','暴击'],
 '高速控制':['速度','命中','生命','免疫'],
 '生存辅助':['速度','反击','生命','防御','抵抗','免疫','保护'],
 '攻击非暴击':['速度','攻击','反击','免疫','抵抗']}

def library_url(hero):
    return 'https://fribbels.github.io/e7/hero-library.html?hero='+quote_plus(hero.get('name_en') or hero['name'])

def candidate_rows(gear,heroes,catalog,base,mode,limit=25):
    gear=copy.deepcopy(gear);gear.set_name=canonical(gear.set_name)
    lookup={fold(h['name_en']):h for h in catalog['heroes']}
    heroes=enrich_profiles(heroes,catalog,gear)
    for h in heroes:
        h['sets']=[canonical(s) for s in h.get('sets',[])]
        explicit=bool(h.get('sets'));h.setdefault('_set_basis','角色配装档案' if explicit else '玩法模板')
        if not explicit and not h.get('_sets_defined'):h['sets']=STYLE_SETS.get(h.get('archetype'),[])
    profiles={fold(h['name']):h for h in heroes}
    if mode in ('role','custom'):
        import scoring_settings
        scorer=(lambda stat,hero_base:scoring_settings.score_stat(stat,hero_base,gear)) if mode=='custom' else None
        rows=recommend(gear,heroes,{**DEFAULT_RULES,'flat_reference':base,'weights':WEIGHTS},score_func=scorer)
    else:
        scores={p['key']:p['score'] for p in breakdown(gear,score_mode='gs')};rows=[]
        for hero in heroes:
            weights=hero.get('weights') or ARCHETYPES.get(hero.get('archetype'),{})
            effective=sum(value*weights.get(key,0) for key,value in scores.items())
            rows.append({'name_en':hero['name'],'name':hero['name'],'archetype':hero.get('archetype','用途参考'),'effective':round(effective,1),'rank':effective})
        rows.sort(key=lambda row:row['rank'],reverse=True)
    for row in rows:
        hero=lookup.get(fold(row.get('name_en',row['name'])))
        row['hero']=hero
        name=hero['name'] if hero else row['name']
        name=re.sub(r'\s*[（(][A-Za-z .-]+[)）]','',name)
        if hero and not re.search('[\u4e00-\u9fff]',name):name=next((a for a in hero.get('aliases',[]) if re.search('[\u4e00-\u9fff]',a)),name)
        row['display_name']=name
        profile=profiles.get(fold(row.get('name_en',row['name'])),{})
        sets=profile.get('sets',[])
        row['demand_basis']=profile.get('_demand_basis',profile.get('_set_basis','无词条需求资料'))
        row['set_match']=bool(gear.set_name and gear.set_name in sets)
        row['set_note']=('套装未识别' if not gear.set_name else
            f"{display_set(gear.set_name)} · {'适配' if row['set_match'] else '非常用参考'} · {profile.get('_set_basis','无配装资料')}")
        if profile.get('_ref_count'):
            row['set_note']+=f"\n样本 {profile['_ref_count']} · {profile['_ref_date']}"
            row['rank']+=5*profile.get('_set_rate',0)
        if mode=='gs' and row['set_match']:row['rank']+=3
    rows.sort(key=lambda row:row['rank'],reverse=True)
    return rows if limit is None else rows[:limit]

class CandidatePanel(tk.Frame):
    def __init__(self,parent,data_dir,on_select):
        super().__init__(parent,bg='#202630',width=310)
        self.pack_propagate(False);self.data_dir=Path(data_dir);self.on_select=on_select;self.photos={}
        tk.Label(self,text='当前装备适配角色',bg='#202630',fg='#edf2fa',font=('Microsoft YaHei UI',13,'bold')).pack(anchor='w',padx=14,pady=(14,4))
        tk.Label(self,text='词条＋套装匹配 · 点击选用\n右键查看配装中位数参考',bg='#202630',fg='#929db0',font=('Microsoft YaHei UI',8),wraplength=280).pack(anchor='w',padx=14,pady=(0,10))
        scroll=ttk.Scrollbar(self);scroll.pack(side='right',fill='y')
        self.canvas=tk.Canvas(self,bg='#202630',highlightthickness=0,yscrollcommand=scroll.set);self.canvas.pack(fill='both',expand=True);scroll.configure(command=self.canvas.yview)
        self.body=tk.Frame(self.canvas,bg='#202630');window=self.canvas.create_window(0,0,window=self.body,anchor='nw')
        self.body.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(window,width=e.width))
    def show_reference(self,hero):
        from reference_window import show_reference
        show_reference(self.winfo_toplevel(),hero)
    def update_rows(self,rows):
        for widget in self.body.winfo_children():widget.destroy()
        for row in rows:
            hero=row.get('hero');image=None
            if hero:
                if hero['id'] not in self.photos:
                    with Image.open(self.data_dir/hero['portrait']) as source:self.photos[hero['id']]=ImageTk.PhotoImage(source.convert('RGBA').resize((40,40)),master=self)
                image=self.photos[hero['id']]
            text=f"{row['display_name']}\n{row['archetype']} · 有效分 {row['effective']:g}\n{row.get('set_note','')}"
            button=tk.Button(self.body,text=text,image=image,compound='left',anchor='w',justify='left',wraplength=218,font=('Microsoft YaHei UI',9),bg='#272e3b',fg='#edf2fa',activebackground='#34465b',activeforeground='white',relief='flat',padx=10,pady=10,borderwidth=0,highlightthickness=1,highlightbackground='#2b3e55',cursor='hand2',command=lambda h=hero:self.on_select(h) if h else None)
            button.pack(fill='x',padx=10,pady=5)
            button.bind('<Enter>',lambda e:e.widget.configure(bg='#2b4059',highlightbackground='#4b73ff'))
            button.bind('<Leave>',lambda e:e.widget.configure(bg='#272e3b',highlightbackground='#2b3e55'))
            if hero:button.bind('<Button-3>',lambda e,h=hero:self.show_reference(h))
        if not rows:tk.Label(self.body,text='读取装备后显示候选',bg='#202630',fg='#929db0').pack(padx=12,pady=20)
