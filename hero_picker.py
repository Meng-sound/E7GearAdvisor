"""Offline portrait-and-name picker, using a consistent max-awakened data state."""
import json
import unicodedata
from pathlib import Path
import tkinter as tk
from tkinter import ttk,simpledialog
from PIL import Image,ImageTk

def load_catalog(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    for hero in data['heroes']:
        if not all(isinstance(hero['base'].get(k),(int,float)) and hero['base'][k]>0 for k in ('atk','hp','def')):raise ValueError('角色基础值缺失：'+hero['name'])
    return data

def merge_user_aliases(catalog,path):
    try:aliases=json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):return
    if not isinstance(aliases,dict):return
    for hero in catalog['heroes']:
        extra=aliases.get(hero['id'],[])
        if isinstance(extra,list):hero['aliases']=list(dict.fromkeys([*hero.get('aliases',[]),*[a for a in extra if isinstance(a,str) and 0<len(a)<=40]]))

def search_heroes(heroes,query):
    def fold(text):return ''.join(c for c in unicodedata.normalize('NFKC',text).casefold() if c.isalnum())
    key=fold(query)
    if not key:return list(heroes)
    found=[]
    for hero in heroes:
        tokens=[hero['name'],hero['name_en'],hero['id'],*hero.get('aliases',[])]
        normalized=[fold(t) for t in tokens]
        if any(key in token for token in normalized):found.append((0 if key in normalized else 1,hero))
    return [h for _,h in sorted(found,key=lambda item:item[0])]

FILTER_GROUPS=(('属性','element',[('', '全部'),('fire','火'),('ice','水'),('wind','木'),('light','光'),('dark','暗')]),
    ('职业','role',[('', '全部'),('warrior','战士'),('knight','骑士'),('assassin','盗贼'),('ranger','射手'),('mage','魔导士'),('manauser','精灵师')]),
    ('星级','stars',[('', '全部'),('5','★5'),('4','★4'),('3','★3')]))

def filter_heroes(heroes,query='',element='',role='',stars=''):
    return [h for h in search_heroes(heroes,query) if
        (not element or h.get('element')==element) and
        (not role or h.get('role')==role) and
        (not stars or str(h.get('stars',''))==str(stars))]

class HeroPicker(tk.Toplevel):
    PAGE_SIZE=9
    def __init__(self,parent,catalog,data_dir,on_select,*,multiple=False,selected_ids=None,selection_label='已选',selection_color='#284c70'):
        super().__init__(parent)
        self.multiple=multiple;self.selected_ids=set(selected_ids or ());self.selection_label=selection_label;self.selection_color=selection_color
        self.title('选择角色 · 自动填入基础属性');self.configure(bg='#171b23')
        self.geometry(f'920x{min(760,self.winfo_screenheight()-90)}');self.minsize(780,580)
        self.catalog=catalog;self.data_dir=Path(data_dir);self.on_select=on_select;self.photos={};self.page=0;self.matches=catalog['heroes']
        self.search=tk.StringVar();self.count=tk.StringVar()
        self.speed_origin=tk.StringVar(value='基础速度');self.speed_min=tk.StringVar();self.speed_max=tk.StringVar()
        self.filters={key:tk.StringVar(value='') for _,key,_ in FILTER_GROUPS};self.filter_buttons={};self.filter_photos={}
        self.PAGE_SIZE=6 if self.winfo_screenheight()<800 else 9
        head=ttk.Frame(self,padding=12);head.pack(fill='x')
        ttk.Label(head,text='中文 / 英文 / 外号').pack(side='left',padx=(0,10))
        entry=ttk.Entry(head,textvariable=self.search);entry.pack(side='left',fill='x',expand=True);entry.focus_set()
        ttk.Button(head,text='清空',command=lambda:self.search.set('')).pack(side='left',padx=(8,0))
        ttk.Button(head,text='新增角色',command=lambda:parent.edit_hero(True)).pack(side='left',padx=(8,0))
        ttk.Button(head,text='编辑所选',command=parent.edit_hero).pack(side='left',padx=(8,0))
        ttk.Button(head,text='外号设置',command=self.edit_selected_alias).pack(side='left',padx=(8,0))
        filters=ttk.Frame(self,padding=(14,0,14,2));filters.pack(fill='x')
        for label,key,options in FILTER_GROUPS:
            line=ttk.Frame(filters);line.pack(fill='x',pady=2)
            ttk.Label(line,text=label,width=5).pack(side='left')
            for value,title in options:
                icon=None;path=self.data_dir/'filter-icons'/f'{key}-{value}.png'
                if value and path.exists():
                    with Image.open(path) as im:self.filter_photos[key,value]=ImageTk.PhotoImage(im.convert('RGBA').resize((24,24),Image.Resampling.LANCZOS),master=self)
                    icon=self.filter_photos[key,value]
                button=tk.Button(line,text=title,image=icon,compound='left',font=('Microsoft YaHei UI',9),bg='#272e3b',fg='#edf2fa',activebackground='#34465f',activeforeground='white',relief='flat',borderwidth=0,highlightthickness=1,padx=8,pady=2,cursor='hand2',command=lambda k=key,v=value:self.set_filter(k,v))
                button.pack(side='left',padx=(0,6));self.filter_buttons[key,value]=button
        speed=ttk.Frame(self,padding=(14,3));speed.pack(fill='x')
        ttk.Combobox(speed,textvariable=self.speed_origin,values=['基础速度','参考面板速度'],state='readonly',width=13).pack(side='left')
        ttk.Label(speed,text='最低').pack(side='left',padx=(8,3));ttk.Entry(speed,textvariable=self.speed_min,width=7).pack(side='left')
        ttk.Label(speed,text='最高').pack(side='left',padx=(8,3));ttk.Entry(speed,textvariable=self.speed_max,width=7).pack(side='left')
        ttk.Label(speed,text='参考速度缺失时不参与筛选',foreground='#929db0').pack(side='left',padx=8)
        for var in (self.speed_origin,self.speed_min,self.speed_max):var.trace_add('write',self.filter)
        ttk.Label(self,text='6星60级满觉醒 · 左键选择角色 · 右键查看配装面板参考',foreground='#929db0',padding=(14,4)).pack(fill='x')
        if self.multiple:
            self.title(selection_label+'英雄 · 多选（再次点击取消）')
            chosen=ttk.Frame(self,padding=(14,3));chosen.pack(fill='x');self.selection_text=tk.Text(chosen,height=2,wrap='word',bg='#202630',fg='#b8d8ff',font=('Microsoft YaHei UI',9),relief='flat',state='disabled')
            bar=ttk.Scrollbar(chosen,command=self.selection_text.yview);bar.pack(side='right',fill='y');self.selection_text.configure(yscrollcommand=bar.set);self.selection_text.pack(fill='x',expand=True)
        self.grid=ttk.Frame(self,padding=10);self.grid.pack(fill='both',expand=True)
        for col in range(3):self.grid.columnconfigure(col,weight=1,uniform='hero')
        for row in range(self.PAGE_SIZE//3):self.grid.rowconfigure(row,weight=1,uniform='hero')
        foot=ttk.Frame(self,padding=10);foot.pack(side='bottom',before=self.grid,fill='x')
        self.prev=ttk.Button(foot,text='上一页',command=lambda:self.change_page(-1));self.prev.pack(side='left')
        ttk.Label(foot,textvariable=self.count).pack(side='left',expand=True)
        self.next=ttk.Button(foot,text='下一页',command=lambda:self.change_page(1));self.next.pack(side='right')
        if self.multiple:ttk.Button(foot,text='完成选择',command=self.destroy).pack(side='right',padx=8)
        self.search.trace_add('write',self.filter);self.filter();self.transient(parent)
        self.bind('<Configure>',self.resize_cards,add='+')
        self.update_idletasks();parent.update_idletasks()
        width=min(920,self.winfo_screenwidth()-24);height=min(760,self.winfo_screenheight()-70)
        right=parent.winfo_rootx()+parent.winfo_width()+8
        left=parent.winfo_rootx()-width-8
        x=right if right+width<=self.winfo_screenwidth()-10 else left if left>=10 else max(10,min(parent.winfo_rootx(),self.winfo_screenwidth()-width-10))
        y=max(10,min(parent.winfo_rooty(),self.winfo_screenheight()-height-40))
        self.geometry(f'{width}x{height}+{x}+{y}')

    def filter(self,*_):
        self.matches=filter_heroes(self.catalog['heroes'],self.search.get(),**{k:v.get() for k,v in self.filters.items()});self.page=0
        if self.speed_min.get().strip() or self.speed_max.get().strip():
            try:
                low=float(self.speed_min.get()) if self.speed_min.get().strip() else 0;high=float(self.speed_max.get()) if self.speed_max.get().strip() else float('inf')
                from build_reference import references,primary_reference
                refs=references().get('heroes',{})
                def speed(hero):
                    if self.speed_origin.get()=='基础速度':return hero['base']['spd']
                    return primary_reference(refs.get(hero['name_en'],{})).get('panel',{}).get('spd')
                self.matches=[h for h in self.matches if speed(h) is not None and low<=speed(h)<=high]
            except (ValueError,TypeError):self.matches=[]
        for (key,value),button in self.filter_buttons.items():
            selected=self.filters[key].get()==value
            button.configure(bg='#4b73ff' if selected else '#272e3b',fg='#171b23' if selected else '#edf2fa',highlightbackground='#4b73ff' if selected else '#34465f')
        self.render()

    def resize_cards(self,event):
        if event.widget is not self:return
        size=6 if event.height<720 else 9
        if self.PAGE_SIZE!=size:
            self.PAGE_SIZE=size;self.after_idle(self.render)

    def set_filter(self,key,value):
        self.filters[key].set(value);self.filter()

    def change_page(self,delta):
        self.page+=delta;self.render()

    def photo(self,hero):
        if hero['id'] not in self.photos:
            with Image.open(self.data_dir/hero['portrait']) as source:
                image=source.convert('RGBA');image.thumbnail((54,54),Image.Resampling.LANCZOS)
                self.photos[hero['id']]=ImageTk.PhotoImage(image,master=self)
        return self.photos[hero['id']]

    def render(self):
        for child in self.grid.winfo_children():child.destroy()
        for row in range(3):self.grid.rowconfigure(row,weight=1 if row<self.PAGE_SIZE//3 else 0,minsize=0)
        self.hero_buttons={}
        if self.multiple:
            names=[h['name'] for h in self.catalog['heroes'] if h['id'] in self.selected_ids]
            self.selection_text.configure(state='normal');self.selection_text.delete('1.0','end');self.selection_text.insert('1.0',f'{self.selection_label}（{len(names)}）：'+('、'.join(names) or '无'));self.selection_text.configure(state='disabled')
        count=len(self.matches);pages=max(1,(count+self.PAGE_SIZE-1)//self.PAGE_SIZE)
        self.page=min(max(self.page,0),pages-1)
        self.count.set(f'{count}个角色 · 第{self.page+1}/{pages}页')
        self.prev.configure(state='normal' if self.page else 'disabled');self.next.configure(state='normal' if self.page+1<pages else 'disabled')
        for i,hero in enumerate(self.matches[self.page*self.PAGE_SIZE:(self.page+1)*self.PAGE_SIZE]):
            base=hero['base'];text=f"{hero['name']}\n攻 {base['atk']:g}  生 {base['hp']:g}\n防 {base['def']:g}  速 {base['spd']:g}\n暴击 {base['crit']:g}% 暴伤 {base['cdmg']:g}%\n命中 {base['eff']:g}% 抗性 {base['res']:g}%\n夹攻 {base['dual']:g}%"
            button=tk.Button(self.grid,text=text,image=self.photo(hero),compound='left',anchor='w',wraplength=200,font=('Microsoft YaHei UI',10),bg='#202630',fg='#edf2fa',activebackground='#34465f',activeforeground='#ffffff',relief='flat',padx=12,pady=8,borderwidth=0,highlightthickness=1,highlightbackground='#2b3e55',cursor='hand2',command=lambda h=hero:self.choose(h))
            button.grid(row=i//3,column=i%3,sticky='nsew',padx=4,pady=4)
            self.hero_buttons[hero['id']]=button;self.paint_selection(button,hero['id'])
            button.bind('<Enter>',lambda e,hid=hero['id']:self.paint_selection(e.widget,hid,True))
            button.bind('<Leave>',lambda e,hid=hero['id']:self.paint_selection(e.widget,hid))
            button.bind('<Button-3>',lambda e,h=hero:self.show_reference(h))
        if not count:ttk.Label(self.grid,text='没有匹配角色，试试英文名或部分中文名。').grid(row=0,column=0,columnspan=3)

    def choose(self,hero):
        if self.multiple:
            self.selected_ids.symmetric_difference_update({hero['id']});self.on_select(hero);self.render()
        else:self.on_select(hero);self.destroy()

    def paint_selection(self,button,hero_id,hover=False):
        selected=self.multiple and hero_id in self.selected_ids
        button.configure(bg=self.selection_color if selected else '#243a50' if hover else '#202630',highlightbackground='#91bdff' if selected else '#4b73ff' if hover else '#2b3e55',highlightthickness=2 if selected else 1)

    def show_reference(self,hero):
        from reference_window import show_reference
        self.reference_window=show_reference(self.master,hero)
        self.reference_window.transient(self)
        return 'break'

    def edit_selected_alias(self):
        hero=self.matches[0] if len(self.matches)==1 else next((h for h in self.catalog['heroes'] if h['id']==getattr(self.master,'selected_hero_id',None)),None)
        if hero is None:
            from tkinter import messagebox
            messagebox.showinfo('先指定角色','请先搜索到唯一角色，或先在主界面选择角色，再设置外号。',parent=self);return
        self.add_alias(hero)

    def add_alias(self,hero):
        text=simpledialog.askstring('补充外号',hero['name']+'：输入外号，多个外号用逗号分隔。',parent=self)
        if not text:return
        words=[w.strip() for w in text.replace('，',',').split(',') if 0<len(w.strip())<=40]
        path=getattr(self.master,'alias_path',None)
        if not path:return
        path=Path(path)
        try:data=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):data={}
        if not isinstance(data,dict):data={}
        data[hero['id']]=list(dict.fromkeys([*data.get(hero['id'],[]),*words]))
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        hero['aliases']=list(dict.fromkeys([*hero.get('aliases',[]),*words]));self.search.set(words[0] if words else hero['name'])
