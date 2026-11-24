"""Compact native layout: hero bases, one score, six profiles, four substats."""
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageTk
from quality_profiles import QUALITY_NAMES
from core import LABELS,SLOTS,SETS

from ui_theme import BG,CARD,FIELD,TEXT,MUTED,ACCENT,GOLD,FONT,EDGE,dark_title

class RoundedCard(tk.Canvas):
    def __init__(self,parent,height=100,color=CARD,padding=16):
        super().__init__(parent,height=height,bg=BG,highlightthickness=0,bd=0)
        self.color=color;self.padding=padding
        self.inner=tk.Frame(self,bg=color)
        self.shape=self.create_polygon(0,0,1,0,1,1,0,1,fill=color,outline='#29464a' if color=='#202d44' else '#24354b',width=1,smooth=True,splinesteps=24)
        self.window=self.create_window(padding,padding,window=self.inner,anchor='nw')
        self.bind('<Configure>',self.resize)
    def resize(self,event):
        w,h=event.width,event.height;r=18
        self.coords(self.shape,r,0,w-r,0,w,0,w,r,w,h-r,w,h,w-r,h,r,h,0,h,0,h-r,0,r,0,0)
        self.itemconfigure(self.window,width=max(1,w-self.padding*2),height=max(1,h-self.padding*2))

class ModernLayout:
    def _style(self):
        style=ttk.Style(self);style.theme_use('clam')
        style.configure('.',font=(FONT,10),background=CARD,foreground=TEXT)
        style.configure('TFrame',background=BG);style.configure('Card.TFrame',background=CARD)
        style.configure('TLabel',background=BG,foreground=TEXT)
        style.configure('Game.TLabel',background=CARD,foreground='#a5c6da',font=(FONT,9))
        style.configure('Compact.TEntry',padding=(4,3))
        style.configure('Compact.TCombobox',padding=(4,3))
        style.configure('TEntry',fieldbackground=FIELD,foreground=TEXT,insertcolor=ACCENT,padding=5,bordercolor=FIELD,lightcolor=FIELD,darkcolor=FIELD)
        style.configure('TCombobox',fieldbackground=FIELD,foreground=TEXT,arrowcolor=MUTED,padding=5,bordercolor=FIELD,lightcolor=FIELD,darkcolor=FIELD)
        style.map('TCombobox',fieldbackground=[('readonly',FIELD)],foreground=[('readonly',TEXT)])
        style.configure('TButton',background=FIELD,foreground=TEXT,padding=(13,9),borderwidth=0,font=(FONT,10))
        style.map('TButton',background=[('pressed','#304b60'),('active','#2b4059')],foreground=[('disabled','#61748c')])
        style.configure('Compact.TButton',background=FIELD,foreground=TEXT,padding=(9,5),font=(FONT,9))
        style.configure('Accent.TButton',background=ACCENT,foreground=TEXT,padding=(12,8),font=(FONT,11,'bold'))
        style.map('Accent.TButton',background=[('active','#6285ff')])
        style.configure('Read.TButton',background=ACCENT,foreground='#ffffff',padding=(9,5),font=(FONT,9,'bold'),borderwidth=0)
        style.map('Read.TButton',background=[('disabled',FIELD),('pressed','#3659d9'),('active','#6285ff')],foreground=[('disabled',MUTED)])
        style.configure('Horizontal.TProgressbar',background=ACCENT,troughcolor=FIELD,bordercolor=BG,lightcolor=ACCENT,darkcolor=ACCENT)
        self.bind_all('<Map>',lambda e:dark_title(e.widget) if isinstance(e.widget,(tk.Tk,tk.Toplevel)) else None,add='+')
        style.configure('TCheckbutton',background=CARD,foreground=TEXT)
        style.configure('TNotebook',background=BG,borderwidth=0,bordercolor=BG,lightcolor=BG,darkcolor=BG);style.configure('TNotebook.Tab',background=CARD,foreground=MUTED,padding=(13,11),font=(FONT,10),bordercolor=BG,lightcolor=BG,darkcolor=BG)
        style.map('TNotebook.Tab',foreground=[('selected',TEXT)],background=[('selected',ACCENT)])
        style.configure('Treeview',background=CARD,fieldbackground=CARD,foreground=TEXT,rowheight=44)
        style.configure('Treeview.Heading',background=FIELD,foreground=MUTED,padding=9,font=(FONT,10,'bold'))
        style.map('Treeview',background=[('selected','#2b5261')],foreground=[('selected','#edf2fa')])
        style.configure('Vertical.TScrollbar',background='#2b4057',troughcolor=BG,borderwidth=0,arrowcolor=MUTED,width=11)
        self.option_add('*TCombobox*Listbox.background',FIELD);self.option_add('*TCombobox*Listbox.foreground',TEXT)

    def _build(self):
        from pathlib import Path
        root=Path(__file__).parent
        self.iconbitmap(str(root/'data/diche.ico'));self._app_icon=tk.PhotoImage(file=str(root/'data/diche-icon.png'));self.iconphoto(True,self._app_icon)
        self.status_label=tk.Label(self,textvariable=self.status,bg=BG,fg=MUTED,font=(FONT,8),wraplength=402,anchor='w',justify='left');self.status_label.pack(side='bottom',fill='x',padx=12,pady=(3,7))
        from app_version import VERSION
        from game_window_ui import GameWindowControls

        header = tk.Frame(self, bg='#0e1b2c', highlightthickness=1, highlightbackground='#244862')
        header.pack(fill='x', padx=12, pady=(10, 5))
        self._brand_image = ImageTk.PhotoImage(Image.open(root/'data/diche-icon.png').resize((26, 26)), master=self)
        tk.Label(header, image=self._brand_image, bg='#0e1b2c').pack(side='left', padx=(9, 5))
        tk.Label(header, text='装备强化计算器', font=(FONT, 13, 'bold'),
                 bg='#0e1b2c', fg=TEXT).pack(side='left', pady=7)
        ttk.Button(header, text='检查更新', style='Compact.TButton',
                   command=self.check_software_update).pack(side='right', padx=7)
        tk.Label(header, text=VERSION, bg='#0e1b2c', fg='#79d8ec',
                 font=('Consolas', 9)).pack(side='right')
        nav=tk.Frame(self,bg=BG);nav.pack(fill='x',padx=12,pady=(0,3))
        self.main_navigation=nav
        actions=[('装备识别',lambda:self.main_canvas.yview_moveto(0)),('角色总分计算',self.open_character_bs),('团战 GVG',self.open_guild_war),('制作 / 重铸',self.open_craft),('选择英雄',self.choose_hero),('设置 / 数据',self.open_details)]
        self.main_nav_buttons=[]
        for i,(label,command) in enumerate(actions):
            nav.columnconfigure(i%3,weight=1,uniform='nav')
            button=ttk.Button(nav,text=label,style='Compact.TButton',command=command)
            button.grid(row=i//3,column=i%3,sticky='ew',padx=2,pady=2);self.main_nav_buttons.append(button)
        from task_replay_ui import open_task_replay
        self.task_nav_buttons=[]
        for i,(mode,label) in enumerate([('shop','刷商店'),('story','推图'),('theater','月光剧场')]):
            button=ttk.Button(nav,text=label,style='Compact.TButton',command=lambda m=mode:open_task_replay(self,m))
            button.grid(row=2,column=i,sticky='ew',padx=2,pady=2);self.task_nav_buttons.append(button)
        self.game_window_controls = GameWindowControls(self)
        self.game_window_controls.pack(fill='x', padx=12, pady=(1, 3))
        self.main_area=tk.Frame(self,bg=BG);self.main_area.pack(fill='both',expand=True)
        self.candidate_sidebar=__import__('candidate_panel').CandidatePanel(self.main_area,root/'data',self.apply_hero)
        self.main_scroll=ttk.Scrollbar(self.main_area,orient='vertical');self.main_scroll.pack(side='right',fill='y')
        canvas=tk.Canvas(self.main_area,bg=BG,highlightthickness=0,yscrollcommand=self.main_scroll.set);canvas.pack(side='left',fill='both',expand=True);self.main_scroll.configure(command=canvas.yview)
        outer=tk.Frame(canvas,bg=BG);window=canvas.create_window(12,10,window=outer,anchor='nw')
        self.main_outer=outer
        outer.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=max(1,e.width-24)))
        self.main_canvas=canvas
        def wheel(event):
            widget=event.widget
            while widget is not None:
                if widget==self.candidate_sidebar:
                    self.candidate_sidebar.canvas.yview_scroll(-int(event.delta/120),'units');return 'break'
                widget=getattr(widget,'master',None)
            if event.widget.winfo_toplevel()==self and outer.winfo_reqheight()>canvas.winfo_height():
                canvas.yview_scroll(-int(event.delta/120),'units');return 'break'
        self.bind_all('<MouseWheel>',wheel,add='+')
        toolbar=tk.Frame(outer,bg=BG);toolbar.pack(fill='x',pady=(0,4))
        toolbar.columnconfigure(0,weight=1,uniform='read-actions');toolbar.columnconfigure(1,weight=1,uniform='read-actions')
        ttk.Button(toolbar,text='读取装备 F8',style='Accent.TButton',command=self.read_screen).grid(row=0,column=0,sticky='nsew',padx=(0,3))
        self.live_button=ttk.Button(toolbar,text='连续读取装备 F9',style='Accent.TButton',command=self.toggle_live);self.live_button.grid(row=0,column=1,sticky='nsew',padx=(3,0))
        columns=tk.Frame(outer,bg=BG);columns.pack(fill='x');columns.columnconfigure(0,weight=1)
        left_column=tk.Frame(columns,bg=BG);left_column.grid(row=0,column=0,sticky='new',padx=(0,8))
        right_column=tk.Frame(columns,bg=BG);right_column.grid(row=1,column=0,sticky='new')
        columns.columnconfigure(1,weight=0,minsize=0)
        left_column.grid_configure(padx=0)
        self.main_columns=columns
        self.hero_card=RoundedCard(left_column,height=180,padding=8);self.hero_card.pack(fill='x',pady=(0,6))
        hero=self.hero_card.inner
        hhead=tk.Frame(hero,bg=CARD);hhead.pack(fill='x')
        ttk.Button(hhead,text='选角色',style='Compact.TButton',command=self.choose_hero).pack(side='left',padx=(0,6))
        self.candidate_toggle=ttk.Button(hhead,text='当前装备适配角色 ▸',style='Compact.TButton',command=self.toggle_candidates);self.candidate_toggle.pack(side='left')
        self.hero_display=ttk.Label(hero,text='通用参考值',font=(FONT,10,'bold'),wraplength=365);self.hero_display.pack(fill='x',pady=(5,0))
        self.character_bs_label=ttk.Label(hero,text='',font=(FONT,9)) # Kept for compatibility; not displayed on the main page.
        values=tk.Frame(hero,bg=CARD);values.pack(fill='x',pady=(3,0));self.base_visible={}
        for key,label in [('atk','基础攻击'),('hp','基础生命'),('def','基础防御'),('spd','速度')]:
            tile=tk.Frame(values,bg=CARD);tile.pack(side='left',fill='x',expand=True)
            tk.Label(tile,text=label,bg=CARD,fg=MUTED,font=(FONT,8)).pack()
            value=tk.Label(tile,textvariable=self.base[key],bg=CARD,fg=TEXT,font=(FONT,12,'bold'));value.pack();self.base_visible[key]=value
        self.extra_stats=tk.Frame(hero,bg=CARD)
        for i,(key,label) in enumerate([('crit','暴击率'),('cdmg','暴击伤害'),('eff','效果命中'),('res','效果抗性'),('dual','夹攻率')]):
            tile=tk.Frame(self.extra_stats,bg=CARD);tile.grid(row=i//3,column=i%3,sticky='ew',pady=3);self.extra_stats.columnconfigure(i%3,weight=1)
            tk.Label(tile,text=label+' %',bg=CARD,fg=MUTED,font=(FONT,8)).pack()
            tk.Label(tile,textvariable=self.base[key],bg=CARD,fg=TEXT,font=(FONT,12,'bold')).pack()
        self.extra_toggle=ttk.Button(hhead,text='更多属性 ▾',style='Compact.TButton',command=self.toggle_base_stats);self.extra_toggle.pack(side='left',padx=(6,0))
        self.panel_reference_button=ttk.Button(hhead,text='面板参考',style='Compact.TButton',command=self.open_selected_reference);self.panel_reference_button.pack(side='left',padx=(6,0))
        hero.bind('<Configure>',lambda e:self.after_idle(self.fit_hero_card))
        from algorithm_modes import MODE_LABELS
        algorithm=tk.Frame(left_column,bg=BG);algorithm.pack(fill='x',pady=(0,5))
        self.algorithm_toolbar=algorithm
        self.score_mode_label=tk.StringVar(value=MODE_LABELS['gs'])
        tk.Label(algorithm,text='算法',bg=BG,fg=MUTED,font=(FONT,9)).pack(side='left',padx=(0,5))
        self.score_mode_selector=ttk.Combobox(algorithm,textvariable=self.score_mode_label,values=tuple(MODE_LABELS.values()),state='readonly',width=20,style='Compact.TCombobox')
        self.score_mode_selector.pack(side='left',fill='x',expand=True)
        self.score_mode_selector.bind('<<ComboboxSelected>>',lambda e:self.score_mode.set(next(key for key,label in MODE_LABELS.items() if label==self.score_mode_label.get())))
        ttk.Button(algorithm,text='编辑算法',style='Compact.TButton',command=self.open_scoring_config).pack(side='left',padx=(5,3))
        ttk.Button(algorithm,text='门槛',style='Compact.TButton',command=self.open_threshold_config).pack(side='left')
        self.result_card=RoundedCard(left_column,height=168,padding=12,color='#202d44');self.result_card.pack(fill='x',pady=(0,6))
        result=self.result_card.inner
        row=tk.Frame(result,bg='#202d44');row.pack(fill='x')
        left=tk.Frame(row,bg='#202d44');left.pack(side='left',padx=(0,12))
        self.score_caption=tk.Label(left,text='角色换算分',bg='#202d44',fg=MUTED,font=(FONT,9))
        self.score_caption.pack(anchor='w',pady=(0,2))
        self.score_value=tk.Label(left,text='—',bg='#202d44',fg=ACCENT,font=(FONT,39,'bold'));self.score_value.pack(anchor='w')
        self.gs_score=tk.Label(left,text='',bg='#202d44',fg=ACCENT,font=(FONT,14,'bold'))
        right=tk.Frame(row,bg='#202d44');right.pack(side='left',fill='both',expand=True)
        self.verdict=tk.Label(right,text='等待装备',bg='#202d44',fg=TEXT,font=(FONT,13,'bold'),anchor='w',wraplength=218,justify='left');self.verdict.pack(anchor='w',pady=(7,4))
        self.scores=tk.Label(right,text='强化 — · 官方分 —',bg='#202d44',fg=MUTED,font=(FONT,8),anchor='w',wraplength=218,justify='left');self.scores.pack(anchor='w')
        self.threshold_label=tk.Label(right,text='当前门槛 —',bg='#202d44',fg=GOLD,font=(FONT,10,'bold'),anchor='w',wraplength=180,justify='left');self.threshold_label.pack(anchor='w',pady=(6,0))
        self.hero_effective=tk.Label(result,text='当前角色有效分：请先选角色',bg='#202d44',fg=ACCENT,font=(FONT,10,'bold'),anchor='w',wraplength=374);self.hero_effective.pack(fill='x',pady=(2,0))
        self.reason=tk.Label(result,text='读取强化界面或背包右侧详情。',bg='#202d44',fg=TEXT,font=(FONT,9),wraplength=374,anchor='w',justify='left');self.reason.pack(fill='x',pady=(4,0))
        self.recognition_label=tk.Label(result,text='',bg='#202d44',fg=GOLD,font=(FONT,9),wraplength=374,anchor='w',justify='left');
        equipment=RoundedCard(right_column,height=96,padding=8);equipment.pack(fill='x',pady=(0,4))
        self.equipment_card=equipment
        row=tk.Frame(equipment.inner,bg=CARD);row.pack(fill='x')
        for i,(label,var,values,width) in enumerate([('品质',self.quality_choice,QUALITY_NAMES,10),('部位',self.vars['slot'],SLOTS,7),('套装',self.vars['set_name'],SETS,8)]):
            if i==2:
                from set_icons import display,canonical
                self.set_display=tk.StringVar(value=display(var.get()));self.vars['set_name'].trace_add('write',lambda *_:self.set_display.set(display(self.vars['set_name'].get())))
                var=self.set_display;values=[display(s) for s in SETS]
            cell=tk.Frame(row,bg=CARD);cell.pack(side='left',fill='x',expand=True,padx=(0,5))
            tk.Label(cell,text=label,bg=CARD,fg=MUTED,font=(FONT,8)).pack(anchor='w')
            field=ttk.Combobox(cell,textvariable=var,values=values,state='readonly',width=width,style='Compact.TCombobox');field.pack(fill='x')
            if i==0:field.bind('<<ComboboxSelected>>',self.apply_quality)
            if i==2:field.bind('<<ComboboxSelected>>',lambda e:self.vars['set_name'].set(canonical(self.set_display.get())))
        row=tk.Frame(equipment.inner,bg=CARD);row.pack(fill='x',pady=(7,0))
        tk.Label(row,text='强化等级 +',bg=CARD,fg=MUTED,font=(FONT,9)).pack(side='left',padx=(0,6))
        ttk.Entry(row,textvariable=self.vars['enhance'],width=5,style='Compact.TEntry').pack(side='left')
        tk.Label(row,text='官方分',bg=CARD,fg=MUTED,font=(FONT,9)).pack(side='left',padx=(20,5))
        ttk.Entry(row,textvariable=self.vars['screen_score'],width=5,style='Compact.TEntry').pack(side='left')
        self.stats_section=tk.Frame(right_column,bg=BG);self.stats_section.pack(fill='x')
        tk.Label(self.stats_section,text='副属性',bg=BG,fg=TEXT,font=(FONT,10,'bold'),anchor='w').pack(fill='x',pady=(0,3))
        self.stat_points=[];self.stat_cards=[]
        for key,value in zip(self.sub_keys,self.sub_values):
            card=RoundedCard(self.stats_section,height=40,padding=6);card.pack(fill='x',pady=(0,2));self.stat_cards.append(card)
            ttk.Combobox(card.inner,textvariable=key,values=['']+list(LABELS.values()),state='readonly',width=16,style='Compact.TCombobox').pack(side='left',fill='x',expand=True,padx=(0,7))
            ttk.Entry(card.inner,textvariable=value,width=6,justify='center',style='Compact.TEntry').pack(side='left')
            points=tk.Label(card.inner,text='— 分',bg=CARD,fg=ACCENT,font=(FONT,9,'bold'),width=7,anchor='e');points.pack(side='right',padx=(4,0));self.stat_points.append(points)
        self.reforge_changes=tk.Label(self.stats_section,text='',bg=BG,fg=TEXT,font=(FONT,10),justify='left',anchor='w')
        self.main_calculations=tk.Label(right_column,text='读取后显示计算明细',bg=BG,fg=MUTED,font=(FONT,9),wraplength=390,justify='left',anchor='w')
        self.calculations_toggle=ttk.Button(right_column,text='计算明细 ▾',style='Compact.TButton',command=self.toggle_calculations);self.calculations_toggle.pack(fill='x',pady=(3,4))
        footer=tk.Frame(right_column,bg=BG);footer.pack(fill='x',pady=(3,5))
        self.main_footer=footer
        ttk.Button(footer,text='导入截图',style='Compact.TButton',command=self.open_image).pack(side='left',fill='x',expand=True,padx=(0,6))
        ttk.Button(footer,text='换一件',style='Compact.TButton',command=self.new_item).pack(side='left',fill='x',expand=True)
        self.calculations_toggle.destroy();self.calculations_toggle=ttk.Button(footer,text='计算明细 ▾',style='Compact.TButton',command=self.toggle_calculations);self.calculations_toggle.pack(side='left',fill='x',expand=True,padx=(6,0))
        result.bind('<Configure>',lambda e:(self.reason.configure(wraplength=max(200,e.width-2)),self.recognition_label.configure(wraplength=max(200,e.width-2)),self.request_result_fit()))
        right.bind('<Configure>',lambda e:(self.verdict.configure(wraplength=max(100,e.width-2)),self.scores.configure(wraplength=max(100,e.width-2)),self.threshold_label.configure(wraplength=max(100,e.width-2)),self.request_result_fit()))
        self.bind('<Configure>',lambda e:self.status_label.configure(wraplength=max(300,min(e.width-24,440))) if e.widget==self else None,add='+')
        canvas.bind('<Configure>',lambda e:self.main_calculations.configure(wraplength=max(300,e.width-36)),add='+')
        self._build_advanced()

    def show_reforge_changes(self,gear,after):
        if after:
            for card in self.stat_cards:card.pack_forget()
            lines=[]
            for a,b in zip(gear.subs,after.subs):
                unit='%' if a.key.endswith('_pct') or a.key in {'crit','cdmg','eff','res'} else ''
                lines.append(f'{LABELS[a.key].rstrip("%")}  {a.value:g}{unit}  →  {b.value:g}{unit}')
            self.reforge_changes.configure(text='\n'.join(lines));self.reforge_changes.pack(fill='x',pady=(0,5))
        else:
            self.reforge_changes.pack_forget()
            expected=4
            if gear.enhance is not None:
                if gear.grade=='英雄' and gear.enhance<12:expected=3
                elif gear.grade=='稀有':expected=2+int(gear.enhance>=9)+int(gear.enhance>=12)
            for i,card in enumerate(self.stat_cards):
                if i>=max(expected,len(gear.subs)):card.pack_forget()
                elif not card.winfo_manager():card.pack(fill='x',pady=(0,2))

    def toggle_calculations(self):
        window=tk.Toplevel(self);window.title('当前装备 · 计算明细');window.configure(bg=BG)
        window.geometry(f'{min(900,self.winfo_screenwidth()-60)}x{min(650,self.winfo_screenheight()-90)}')
        text=tk.Text(window,bg=CARD,fg=TEXT,font=(FONT,10),wrap='word',relief='flat',padx=14,pady=12)
        text.pack(fill='both',expand=True);text.insert('1.0',self.main_calculations.cget('text'));text.configure(state='disabled')

    def toggle_base_stats(self):
        if self.extra_stats.winfo_manager():
            self.extra_stats.pack_forget();self.extra_toggle.configure(text='更多属性 ▾');self.hero_card.configure(height=180)
        else:
            self.extra_stats.pack(fill='x');self.extra_toggle.configure(text='收起属性 ▴');self.hero_card.configure(height=290)
        self.after_idle(self.fit_hero_card)

    def fit_hero_card(self):
        required=self.hero_card.inner.winfo_reqheight()+self.hero_card.padding*2+10
        if abs(float(self.hero_card.cget('height'))-required)>1:self.hero_card.configure(height=required)

    def render_summary(self,gear,result,base):
        bykey={item['key']:item['score'] for item in result['breakdown']}
        reverse={label:key for key,label in LABELS.items()}
        for key,label in zip(self.sub_keys,self.stat_points):
            score=bykey.get(reverse.get(key.get()))
            label.configure(text=f'{score:.2f} 分' if score is not None else '— 分')
        self.main_calculations.configure(text='\n'.join(f'{LABELS[item["key"]]}：{item["formula"]} = {item["score"]:.2f}分' for item in result['breakdown'])+f'\n{self.score_caption.cget("text")} {result["score"]:.2f}分'+(f' · 本阶段门槛 {result["threshold"]}' if result.get('threshold') is not None else ''))
        self.request_result_fit()

    def request_result_fit(self):
        if getattr(self,'_result_fit_job',None) is None:self._result_fit_job=self.after_idle(self.fit_result_card)

    def fit_result_card(self):
        self.update_idletasks()
        widgets=[w for w in self.result_card.inner.winfo_children() if w.winfo_manager()]
        height=sum(widget.winfo_reqheight() for widget in widgets)+self.result_card.padding*2+12
        if abs(int(float(self.result_card.cget('height')))-max(150,height))>1:self.result_card.configure(height=max(150,height))
        self._result_fit_job=None
