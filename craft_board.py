"""Compact, numbered decision board with a prominent keep/discard overview."""
import base64,io,json,hashlib,tkinter as tk
from copy import deepcopy
from tkinter import ttk
from PIL import Image,ImageTk
from core import LABELS,SLOTS
from quality_profiles import infer_quality
BG='#0e1522';CARD='#182438';TEXT='#eef4fc';MUTED='#9aaec4';FONT='Microsoft YaHei UI'
COLORS={'keep':('#1b6957','#80e0ca','留'),'discard':('#963b4b','#ff9b9b','分解'),'review':('#876320','#f0cb89','复核')}

class CraftBoard(tk.Toplevel):
    def __init__(self,parent):
        super().__init__(parent);self.app=parent;self.title('装备制作识别');self.configure(bg=BG);self.entries=[];self.photos=[];self.image_cache={};self._last_key=None
        self.protocol('WM_DELETE_WINDOW',self.close_board)
        width=min(1180,self.winfo_screenwidth()-40);height=min(850,self.winfo_screenheight()-90);self.geometry(f'{width}x{height}+25+30');self.minsize(880,610)
        head=tk.Frame(self,bg=BG);head.pack(fill='x',padx=18,pady=(12,7))
        tk.Label(head,text='装备制作识别',bg=BG,fg=TEXT,font=(FONT,18,'bold')).pack(side='left')
        self.summary=tk.Label(head,text='按原图位置对应编号',bg=BG,fg=MUTED,font=(FONT,10));self.summary.pack(side='right')
        tools=tk.Frame(self,bg=BG);tools.pack(fill='x',padx=18,pady=(0,7))
        ttk.Button(tools,text='读取制作装备',style='Read.TButton',command=lambda:parent.read_screen('batch')).pack(side='left',padx=(0,6))
        self.live_button=ttk.Button(tools,text='连续读取 F9',style='Read.TButton',command=parent.toggle_craft_live);self.live_button.pack(side='left',padx=(0,6))
        ttk.Button(tools,text='导入制作截图',style='Compact.TButton',command=parent.open_craft_image).pack(side='left',padx=(0,12))
        tk.Label(tools,text='部位',bg=BG,fg=MUTED,font=(FONT,9)).pack(side='left',padx=(0,5));self.slot=tk.StringVar(value='未指定')
        combo=ttk.Combobox(tools,textvariable=self.slot,values=['未指定']+SLOTS,state='readonly',width=7,style='Compact.TCombobox');combo.pack(side='left');combo.bind('<<ComboboxSelected>>',lambda e:self.refresh_scores())
        self.gate_guide=tk.Label(self,text='',bg=BG,fg=MUTED,font=(FONT,9),anchor='w',wraplength=830);self.gate_guide.pack(fill='x',padx=18,pady=(0,5))
        overview=tk.Frame(self,bg=BG);overview.pack(fill='x',padx=18,pady=(0,8));self.overview_labels={}
        for i,(category,label,weight) in enumerate([('keep','保留',1),('discard','分解',2),('review','复核',1)]):
            fill,color,_=COLORS[category];tile=tk.Frame(overview,bg=fill);tile.grid(row=0,column=i,sticky='nsew',padx=(0,6 if i<2 else 0));overview.columnconfigure(i,weight=weight)
            tk.Label(tile,text=label,bg=fill,fg='white',font=(FONT,10,'bold')).pack(anchor='w',padx=12,pady=(5,0))
            value=tk.Label(tile,text='—',bg=fill,fg='white',font=(FONT,16,'bold'),anchor='w',justify='left',wraplength=530 if i==1 else 250);value.pack(fill='x',padx=12,pady=(0,6));self.overview_labels[category]=value
        self.keep_list=self.overview_labels['keep'];self.discard_list=self.overview_labels['discard'];self.review_list=self.overview_labels['review']
        area=tk.Frame(self,bg=BG);area.pack(fill='both',expand=True,padx=13,pady=(0,4));scroll=ttk.Scrollbar(area);scroll.pack(side='right',fill='y')
        self.canvas=tk.Canvas(area,bg=BG,highlightthickness=0,yscrollcommand=scroll.set);self.canvas.pack(fill='both',expand=True);scroll.configure(command=self.canvas.yview)
        self.body=tk.Frame(self.canvas,bg=BG);self.window=self.canvas.create_window(0,0,window=self.body,anchor='nw')
        self.body.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')));self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.window,width=e.width))
        self.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-int(e.delta/120),'units'))
        self.bind('<F9>',lambda e:parent.toggle_craft_live());self.bind('<F8>',lambda e:parent.read_screen('batch'))
        tk.Label(self,textvariable=parent.status,bg=BG,fg=MUTED,font=(FONT,8),wraplength=1100,anchor='w').pack(fill='x',padx=18,pady=(1,7))
    def set_entries(self,entries):self.entries=entries;self.refresh_scores()
    def refresh_scores(self):
        from threshold_settings import current
        mode=self.app.score_mode.get();route=self.app.route.get()
        c=current(mode);l,r,v=c["left"],c["right"],c["speed"]
        self.gate_guide.configure(text=f'未强化：紫装≥3速保留，红装有速度保留 · 左三件紫{l["purple"]:g}／红{l["red"]:g}分 · 右三件固定主属性不强 · 蓝装分解')
        from craft_window import crafted_decision
        base={k:float(v.get()) for k,v in self.app.base.items()}
        key=(mode,route,json.dumps(c,sort_keys=True),tuple(base.items()),self.slot.get(),json.dumps([e['gear'].to_dict() for e in self.entries],sort_keys=True))
        if key==self._last_key:return
        self._last_key=key
        for widget in self.body.winfo_children():widget.destroy()
        self.photos=[];self.decisions=[];self.decision_labels=[];numbers={'keep':[],'discard':[],'review':[]}
        xs=sorted(set(round(e['box'][0]/25)*25 for e in self.entries));ys=[]
        for entry in self.entries:
            y=entry['box'][1]
            if not any(abs(y-a)<35 for a in ys):ys.append(y)
        ys.sort()
        for col in range(max(1,len(xs))):self.body.columnconfigure(col,weight=1,uniform='crafted')
        for index,entry in enumerate(self.entries):
            gear=deepcopy(entry['gear'])
            if self.slot.get() in SLOTS:gear.slot=self.slot.get()
            decision=crafted_decision(gear,base,mode,route);self.decisions.append(decision);numbers[decision['category']].append(index+1)
            fill,color,label=COLORS[decision['category']]
            row=min(range(len(ys)),key=lambda i:abs(ys[i]-entry['box'][1]));col=min(range(len(xs)),key=lambda i:abs(xs[i]-entry['box'][0]))
            card=tk.Frame(self.body,bg=CARD,highlightbackground=color,highlightthickness=1);card.grid(row=row,column=col,sticky='nsew',padx=5,pady=3)
            badge=tk.Label(card,text=f'{label}  #{index+1:02}',bg=fill,fg='white',font=(FONT,17,'bold'));badge.pack(fill='x');self.decision_labels.append(badge)
            rowbox=tk.Frame(card,bg=CARD);rowbox.pack(fill='x',padx=7,pady=2)
            if entry.get('thumbnail_png'):
                digest=hashlib.blake2b(entry['thumbnail_png'].encode(),digest_size=8).digest()
                if digest not in self.image_cache:
                    with Image.open(io.BytesIO(base64.b64decode(entry['thumbnail_png']))) as image:
                        image=image.convert('RGB');image.thumbnail((130,52));self.image_cache[digest]=ImageTk.PhotoImage(image,master=self)
                photo=self.image_cache[digest];self.photos.append(photo);tk.Label(rowbox,image=photo,bg=CARD).pack(side='left',padx=(0,7))
            meta=tk.Frame(rowbox,bg=CARD);meta.pack(side='left',fill='x',expand=True)
            tk.Label(meta,text=f'{infer_quality(gear.level,gear.grade)}',bg=CARD,fg=MUTED,font=(FONT,8)).pack(anchor='w')
            tk.Label(meta,text=f'{decision["score"]:.2f} 分',bg=CARD,fg=color,font=(FONT,13,'bold')).pack(anchor='w')
            attrs=tk.Frame(card,bg=CARD);attrs.pack(fill='x',padx=7)
            for j,s in enumerate(gear.subs):
                text=LABELS[s.key].rstrip('%')+f'{s.value:g}'+('%' if s.key.endswith('_pct') or s.key in {'crit','cdmg','eff','res'} else '')
                tk.Label(attrs,text=text,bg=CARD,fg=TEXT,font=(FONT,9),anchor='w').grid(row=j//2,column=j%2,sticky='ew',padx=(0,4));attrs.columnconfigure(j%2,weight=1)
            advice=decision['advice'];side='右三件' if gear.slot in {'项链','戒指','鞋子'} else '左三件';grade={'史诗':'红装','英雄':'紫装'}.get(gear.grade,'品质未识别');gate=advice.get('threshold')
            reason='蓝色装备一律分解' if gear.grade=='稀有' else '右三件固定主属性，不推荐强化' if advice.get('blocked_fixed_main') else f'左三件初始速度{advice["speed"]:g}达到自定门槛，留着试强' if decision['category']=='keep' and advice['route']=='追速' else f'{side}·{grade} 达到{gate:g}分门槛' if decision['category']=='keep' and gate is not None else f'{side}·{grade} 未达{gate:g}分门槛' if decision['category']=='discard' and gate is not None else '属性未读全，建议复核'
            if advice.get('speed_retention'):reason=('红装有速度' if gear.grade=='史诗' else '紫装速度≥3')+' · 保留试强'
            elif advice.get('route')=='追速':reason=f'当前{advice["speed"]:g}速 / 速度门槛{advice.get("speed_threshold",v["entry"]):g}；总分{advice["score"]:.2f}'
            tk.Label(card,text=reason,bg=CARD,fg=MUTED,font=(FONT,8),anchor='w').pack(fill='x',padx=7,pady=(3,3))
            ttk.Button(card,text='查看明细',style='Compact.TButton',command=lambda g=gear:self.select(g)).pack(fill='x',padx=7,pady=(0,5))
        for category,label in self.overview_labels.items():label.configure(text=' · '.join(str(n) for n in numbers[category]) or '无')
        self.summary.configure(text=f'共{len(self.entries)}件 · 按原图位置对应编号')
        self._last_key=key
    def select(self,gear):self.app.fill_gear(gear,origin='装备制作识别');self.app.calculate();self.app.lift()
    def close_board(self):self.app.stop_craft_live();self.destroy()
