"""Windows equipment OCR calculator with visible scores and an offline hero picker."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog,messagebox,simpledialog,ttk

from app import RegionSelector
from core import Gear,Stat,Store,LABELS,SLOTS,SETS,import_heroes,recommend,DEFAULT_RULES
from desktop_capture import find_game_windows,select_game_rectangle
import emulator
from ocr import WindowsOCR
from local_ocr import LocalOCR
from craft_window import CraftWindow
from picture_algorithm import evaluate_picture,breakdown,DEFAULT_BASE,WEIGHTS,ROUTES
from advice import evaluate_advice
from candidate_panel import CandidatePanel,candidate_rows
from official_rolls import PROFILES,describe_roll,next_roll_note
from vision import ScreenReader
from hero_picker import HeroPicker,load_catalog,merge_user_aliases
from PIL import Image,ImageTk
from modern_ui import ModernLayout
from hero_stats import ALL_BASE_DEFAULTS
from hero_storage import HeroEditor,user_heroes,merge_catalog,save_user_heroes,import_records
from recognition_check import recognition_notice
from quality_profiles import QUALITY_PROFILES,infer_quality
import adaptation_storage
from build_reference import references,configure_cache
from feature_ui import FeatureMixin
from app_version import VERSION

ROOT=Path(__file__).resolve().parent
USER=Path(os.environ.get('E7_ADVISOR_HOME',str(ROOT/'userdata')))
if (ROOT/'runtime/tcl/tcl8.6/init.tcl').is_file():
    os.environ['TCL_LIBRARY']=str(ROOT/'runtime/tcl/tcl8.6')
    os.environ['TK_LIBRARY']=str(ROOT/'runtime/tcl/tk8.6')
BG='#171b23';PANEL='#202630';FIELD='#272e3b';TEXT='#edf2fa';MUTED='#929db0';GOLD='#f0cb89';GREEN='#4b73ff';RED='#ff9b9b'
FONT='Microsoft YaHei UI'


class PCCalculator(FeatureMixin,ModernLayout,tk.Tk):
    def __init__(self):
        super().__init__()
        USER.mkdir(parents=True,exist_ok=True)
        self.init_extensions(USER)
        self.title('装备强化计算器 · '+VERSION)
        self.geometry(f'{min(500,self.winfo_screenwidth()-50)}x{min(960,self.winfo_screenheight()-85)}');self.minsize(460,min(680,self.winfo_screenheight()-85));self.configure(bg=BG)
        self.db=Store(USER/'pc-observations.sqlite3')
        self.ocr=None;self.pending=queue.Queue();self.busy=False;self.live=False;self.craft_live=False;self.hidden_for_capture=False
        self.region=None;self.sequence=0;self.item_id=None;self.last_fingerprint=None
        self.origin='等待读取';self.updating=False;self.last_gear=None;self.last_decision=None
        self.photo=None;self.last_preview=None
        self.vars={k:tk.StringVar() for k in ['name','slot','set_name','grade','level','enhance','screen_score']}
        self.score_mode=tk.StringVar(value='gs')
        self.quality_choice=tk.StringVar(value='未识别')
        self.main_key=tk.StringVar();self.main_value=tk.StringVar()
        self.sub_keys=[tk.StringVar() for _ in range(4)];self.sub_values=[tk.StringVar() for _ in range(4)]
        self.base={k:tk.StringVar(value=str(v)) for k,v in ALL_BASE_DEFAULTS.items()}
        self.custom_hero_path=USER/'custom-heroes.json'
        self.adaptation_path=USER/'hero-adaptation.json';self.adaptation_load_error=''
        try:adaptation_storage.configure(self.adaptation_path)
        except (OSError,ValueError,TypeError) as exc:self.adaptation_load_error=str(exc)
        configure_cache(USER/'hero-library-cache.json')
        self.hero_catalog=merge_catalog(load_catalog(ROOT/'data/hero-catalog.json'),user_heroes(self.custom_hero_path));self.alias_path=USER/'hero-aliases.json';merge_user_aliases(self.hero_catalog,self.alias_path);self.selected_hero_id=None;self.hero_photo=None;self._changing_base=False;self.picker=None
        self.auto_window=tk.BooleanVar(value=True);self.hide_window=tk.BooleanVar(value=False)
        self.input_mode=tk.StringVar(value=list(emulator.INPUT_MODES)[0])
        self.fixed_bugs=tk.BooleanVar(value=True);self.verified=tk.BooleanVar(value=False)
        self.topmost=tk.BooleanVar(value=False)
        self.route=tk.StringVar(value=ROUTES[0]);self.roll_profile=tk.StringVar(value=PROFILES[0])
        self.reforged=tk.BooleanVar(value=False);self.fixed_main=tk.BooleanVar(value=False)
        self.status=tk.StringVar(value='打开游戏的装备强化页，点击读取并计算；修改数值后自动重新计算。')
        self._style();self._build();self._load_preferences()
        self.input_mode.trace_add('write',lambda *_:self.input_mode_changed())
        self.score_mode.trace_add('write',lambda *_:self.mode_changed())
        self.mode_changed()
        for var in list(self.vars.values())+[self.main_key,self.main_value]+self.sub_keys+self.sub_values:
            var.trace_add('write',self._form_changed)
        for key in ('grade','level'):self.vars[key].trace_add('write',self._raw_quality_edited)
        for var in self.base.values():var.trace_add('write',self._base_edited)
        self.bind('<F8>',lambda e:self.read_screen());self.bind('<F9>',lambda e:self.toggle_live())
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.after(100,self.poll)
        self.refresh_history_selector()
        self.reload_heroes();self.refresh_adaptation_status()
        try:adaptation_storage.configure(self.adaptation_path,self.hero_catalog)
        except (OSError,ValueError,TypeError) as exc:self.adaptation_load_error=str(exc)
        if self.adaptation_load_error:self.status.set('适配配置未载入：'+self.adaptation_load_error)
        self.after(400,self.poll_extensions)
        from software_update_ui import startup_check
        self.after(2500,lambda:startup_check(self))

    def _text(self,parent,height=8):
        return tk.Text(parent,bg=PANEL,fg=TEXT,insertbackground=GOLD,font=(FONT,10),wrap='word',height=height,relief='flat',padx=14,pady=14,spacing1=3,spacing3=5,selectbackground='#2b5261')

    def _write(self,widget,text):
        widget.delete('1.0','end');widget.insert('1.0',text)

    def _button(self,parent,text,command,accent=False):
        b=ttk.Button(parent,text=text,command=command,style='Accent.TButton' if accent else 'TButton');b.pack(side='left',padx=(0,8));return b

    def _build_advanced(self):
        self.details=tk.Toplevel(self);self.details.title('装备强化计算器 · 设置 / 数据');self.details.geometry(f'{min(1120,self.winfo_screenwidth()-50)}x{min(800,self.winfo_screenheight()-85)}');self.details.configure(bg=BG);self.details.withdraw();self.details.protocol('WM_DELETE_WINDOW',self.details.withdraw)
        banner=tk.Frame(self.details,bg=BG);banner.pack(fill='x',padx=22,pady=(18,6))
        tk.Label(banner,text='装备强化计算器',font=(FONT,17,'bold'),bg=BG,fg=TEXT).pack(side='left')
        tk.Label(banner,text='明细 · 角色 · 记录',font=(FONT,10),bg=BG,fg=MUTED).pack(side='right')
        self.update_check_button=ttk.Button(banner,text='检查更新',style='Read.TButton',command=self.check_software_update)
        self.update_check_button.pack(side='right',padx=(8,12))
        self.notebook=ttk.Notebook(self.details);self.notebook.pack(fill='both',expand=True,padx=10,pady=10)
        score_tab=ttk.Frame(self.notebook,style='Card.TFrame',padding=12)
        self.notebook.add(score_tab,text='计算明细')
        self.comparison=self._text(score_tab,15);self.comparison.pack(fill='both',expand=True)
        settings_page=ttk.Frame(self.notebook,padding=12);settings_page.columnconfigure(0,weight=3);settings_page.columnconfigure(1,weight=2)
        settings=ttk.Frame(settings_page);settings.grid(row=0,column=0,sticky='nsew',padx=(0,14))
        settings_extras=ttk.Frame(settings_page);settings_extras.grid(row=0,column=1,sticky='nsew')
        self.settings_page=settings_page
        history_tab=ttk.Frame(self.notebook,style='Card.TFrame',padding=12)
        roles_tab=ttk.Frame(self.notebook,style='Card.TFrame',padding=12)
        rules_tab=ttk.Frame(self.notebook,style='Card.TFrame',padding=12)
        raw_tab=ttk.Frame(self.notebook,style='Card.TFrame',padding=12)
        preview_tab=ttk.Frame(self.notebook,style='Card.TFrame',padding=10)
        for tab,label in [(settings_page,'设置'),(history_tab,'强化记录'),(roles_tab,'角色候选'),(rules_tab,'规则说明'),(raw_tab,'识别原文'),(preview_tab,'面板预览')]:self.notebook.add(tab,text=label)
        ttk.Label(settings,textvariable=self.engine_choice,foreground=GREEN).pack(anchor='w',pady=(0,8))
        self._pair(settings,'装备名称',self.vars['name'])
        row=ttk.Frame(settings,style='Card.TFrame');row.pack(fill='x',pady=5)
        self._mini(row,'原始等级',self.vars['level'],width=8);self._mini(row,'原始品质',self.vars['grade'],['史诗','英雄','稀有'],width=8)
        ttk.Label(settings,text='主属性（不计入民间副属性分）').pack(anchor='w',pady=5)
        self._stat_row(settings,self.main_key,self.main_value)
        row=ttk.Frame(settings,style='Card.TFrame');row.pack(fill='x',pady=7)
        for key,label in [('atk','基础攻击'),('hp','基础生命'),('def','基础防御')]:self._mini(row,label,self.base[key],width=9)
        row=ttk.Frame(settings,style='Card.TFrame');row.pack(fill='x',pady=7)
        for text,callback in [('新增角色',lambda:self.edit_hero(True)),('编辑所选角色',self.edit_hero),('导入角色JSON',self.import_hero_panels),('导出角色JSON',self.export_hero_panels)]:
            ttk.Button(row,text=text,command=callback).pack(side='left',padx=(0,5))
        self._pair(settings,'判断路线',self.route,ROUTES)
        for label,var in [('自动定位游戏窗口（客户端或模拟器）',self.auto_window),('已经重铸（90级自动识别）',self.reforged)]:ttk.Checkbutton(settings,text=label,variable=var).pack(anchor='w',pady=4)
        row=ttk.Frame(settings,style='Card.TFrame');row.pack(fill='x',pady=4)
        ttk.Label(row,text='输入方式').pack(side='left')
        ttk.Combobox(row,textvariable=self.input_mode,values=list(emulator.INPUT_MODES),state='readonly',width=22).pack(side='left',padx=(8,8))
        ttk.Button(row,text='检测窗口/模拟器',command=self.detect_emulator).pack(side='left')
        self.input_status=ttk.Label(settings,text='模拟器点击走原生接口或 ADB，不抢鼠标。',foreground=MUTED,wraplength=560)
        self.input_status.pack(anchor='w',pady=(0,4))
        row=ttk.Frame(settings,style='Card.TFrame');row.pack(fill='x',pady=8)
        self._button(row,'手动框选',self.pick_region);self._button(row,'检查OCR',self.check_ocr);self._button(row,'应用设置',self.calculate)
        row=ttk.Frame(history_tab,style='Card.TFrame');row.pack(fill='x',pady=(0,8))
        self.history_var=tk.StringVar();self.history_selector=ttk.Combobox(row,textvariable=self.history_var,state='readonly',width=28);self.history_selector.pack(side='left',fill='x',expand=True,padx=(0,8));self.history_selector.bind('<<ComboboxSelected>>',self.load_history_item)
        ttk.Button(row,text='导出JSON',command=self.export_history).pack(side='left')
        ttk.Checkbutton(history_tab,text='我已核对当前属性',variable=self.verified).pack(anchor='w')
        ttk.Button(history_tab,text='记录本次读数 / 强化跳值',command=self.record).pack(anchor='w',pady=7)
        self.history_text=self._text(history_tab,14);self.history_text.pack(fill='both',expand=True)
        self.roles_tab=roles_tab
        updates=ttk.Frame(roles_tab,style='Card.TFrame');updates.pack(fill='x',pady=(0,8))
        for label,callback in [('导入 JSON',self.import_adaptation),('导出 JSON',self.export_adaptation),('保存模板',self.save_adaptation_template),('清空自定义',self.confirm_clear_adaptation)]:ttk.Button(updates,text=label,command=callback).pack(side='left',padx=(0,6))
        self.adaptation_status=ttk.Label(updates,text='适配数据',foreground=MUTED);self.adaptation_status.pack(side='right')
        self.roles=ttk.Treeview(roles_tab,columns=('name','play','score'),show='tree headings',height=9)
        self.roles.heading('#0',text='头像');self.roles.column('#0',width=50,minwidth=45,stretch=False)
        for key,label,width in [('name','角色候选',230),('play','玩法类型',145),('score','有效分',110)]:self.roles.heading(key,text=label);self.roles.column(key,width=width,minwidth=60)
        self.roles.pack(fill='both',expand=True)
        ttk.Label(roles_tab,text='社区资料与玩法模板，仅作候选，不代表完整配装或当前最佳搭配。',foreground=MUTED,wraplength=670).pack(anchor='w',pady=9)
        rules=self._text(rules_tab,16);rules.pack(fill='both',expand=True);self._write(rules,self.algorithm_notes())
        self.raw=self._text(raw_tab,18);self.raw.pack(fill='both',expand=True)
        self.preview=ttk.Label(preview_tab,text='读取后显示装备面板');self.preview.pack(fill='both',expand=True)
        self.rules_text=rules
        self.add_feature_controls(settings_extras,roles_tab,banner)


    def mode_changed(self):
        from algorithm_modes import MODE_LABELS
        mode=self.score_mode.get()
        if mode not in MODE_LABELS:return
        self.score_caption.configure(text=MODE_LABELS[mode])
        self.score_mode_label.set(MODE_LABELS[mode])
        if hasattr(self,'heroes'):
            if hasattr(self,'rules_text'):self._write(self.rules_text,self.algorithm_notes())
            self.calculate();self._save_preferences()
            if hasattr(self,'craft_window') and self.craft_window.winfo_exists():
                self.craft_window._last_key=None;self.craft_window.refresh_scores()


    def toggle_candidates(self):
        expanded=bool(getattr(self,'candidates_open',False))
        width=self.winfo_width();height=self.winfo_height();x=self.winfo_x();y=self.winfo_y()
        if expanded:
            self.candidate_sidebar.pack_forget();self.geometry(f'{max(390,width-310)}x{height}+{getattr(self,"_before_sidebar_x",x)}+{y}')
            self.candidate_toggle.configure(text='当前装备适配角色 ▸');self.candidates_open=False
        else:
            self._before_sidebar_x=x
            if x+width+310>self.winfo_screenwidth():x=max(0,x-310)
            self.candidate_sidebar.pack(side='left',fill='both');self.geometry(f'{width+310}x{height}+{x}+{y}')
            self.candidate_toggle.configure(text='收起 ◂');self.candidates_open=True

    def open_details(self):
        self.details.deiconify();self.details.lift()

    def refresh_adaptation_status(self):
        self.adaptation_status.configure(text=f'参考 {len(references().get("heroes",{}))}名 · 自定义 {len(adaptation_storage.overrides())}名')

    def import_adaptation(self):
        path=filedialog.askopenfilename(parent=self.details,filetypes=[('角色装备适配 JSON','*.json')])
        if not path:return
        try:
            count=adaptation_storage.import_file(path,self.adaptation_path,self.hero_catalog)
            self.refresh_adaptation_status();self.calculate();self.status.set(f'已导入{count}名角色适配数据，按角色合并；原配置已备份。')
        except (OSError,ValueError,TypeError,KeyError) as exc:messagebox.showerror('导入失败，原数据未改动',str(exc),parent=self.details)

    def confirm_clear_adaptation(self):
        count=len(adaptation_storage.overrides())
        if not count:
            messagebox.showinfo('清空自定义数据','当前没有自定义角色适配数据。',parent=self.details)
            return
        if not messagebox.askyesno('确认清空自定义数据',
            f'即将清空 {count} 名角色的自定义装备适配配置。\n\n清空后恢复使用 Fribbels 参考和默认规则。\n已同步参考、英雄基础资料、OCR 和算分设置不会删除。\n操作前会自动备份，可通过“导入 JSON”恢复。\n\n确定清空吗？',
            icon='warning',default='no',parent=self.details):return
        try:
            removed,backup=adaptation_storage.clear_custom(self.adaptation_path)
        except OSError as exc:
            messagebox.showerror('清空失败',str(exc),parent=self.details);return
        self.refresh_adaptation_status();self.calculate()
        self.status.set(f'已清空 {removed} 名角色的自定义适配配置；已恢复默认参考。')
        messagebox.showinfo('清空完成',f'已清空 {removed} 名角色的自定义配置。'+(f'\n备份：{backup}\n如需恢复，请点击“导入 JSON”选择该文件。' if backup else ''),parent=self.details)

    def export_adaptation(self):
        path=filedialog.asksaveasfilename(parent=self.details,initialfile='hero-gear-adaptation.json',defaultextension='.json',filetypes=[('角色装备适配 JSON','*.json')])
        if path:Path(path).write_text(json.dumps(adaptation_storage.export_bundle(references()),ensure_ascii=False,indent=2),encoding='utf8');self.status.set('已导出当前参考面板和自定义适配数据。')

    def save_adaptation_template(self):
        path=filedialog.asksaveasfilename(parent=self.details,initialfile='hero-adaptation-template.json',defaultextension='.json',filetypes=[('角色装备适配 JSON','*.json')])
        if path:Path(path).write_text((ROOT/'data/hero-adaptation-template.json').read_text(encoding='utf8'),encoding='utf8');self.status.set('已保存适配数据模板；按角色填写词条权重与套装后导入。')

    def apply_quality(self,event=None):
        profile=QUALITY_PROFILES.get(self.quality_choice.get())
        if not profile:return
        self.updating=True
        try:
            self.vars['grade'].set(profile['grade']);self.vars['level'].set(str(profile['level']))
            self.reforged.set(profile['reforged']);self.roll_profile.set(profile['roll_profile'])
            if profile['level']==90:self.vars['enhance'].set('15')
        finally:self.updating=False
        self.verified.set(False);self.calculate();self.status.set(profile['note'])

    def _raw_quality_edited(self,*_):
        if self.updating:return
        try:level=int(self.vars['level'].get())
        except ValueError:level=None
        choice=infer_quality(level,self.vars['grade'].get())
        self.quality_choice.set(choice)
        profile=QUALITY_PROFILES.get(choice)
        self.reforged.set(bool(profile and profile['reforged']))
        self.roll_profile.set(profile['roll_profile'] if profile else PROFILES[0])

    def _quality_from_gear(self,gear):
        old=self.last_gear
        same=old is not None and old.level==88 and old.name==gear.name and old.slot==gear.slot and old.set_name==gear.set_name
        known=self.quality_choice.get() if same else None
        choice=infer_quality(gear.level,gear.grade,known)
        self.quality_choice.set(choice)
        profile=QUALITY_PROFILES.get(choice)
        self.reforged.set(bool(profile and profile['reforged']))
        self.roll_profile.set(profile['roll_profile'] if profile else PROFILES[0])

    def choose_hero(self):
        if self.picker is not None and self.picker.winfo_exists():self.picker.lift();return
        self.picker=HeroPicker(self,self.hero_catalog,ROOT/'data',self.apply_hero)

    def reload_heroes(self):
        records=user_heroes(self.custom_hero_path)
        catalog=load_catalog(ROOT/'data/hero-catalog.json')
        try:synced=json.loads(self.base_cache_path.read_text(encoding='utf8')).get('heroes',[])
        except (OSError,ValueError):synced=[]
        catalog=merge_catalog(catalog,synced)
        self.hero_catalog=merge_catalog(catalog,records)
        merge_user_aliases(self.hero_catalog,self.alias_path)
        self.heroes=import_heroes(json.loads((ROOT/'data/heroes.json').read_text(encoding='utf-8')))
        profiles={h['name']:h for h in self.heroes}
        for hero in self.hero_catalog['heroes']:
            if hero['name_en'] in profiles:profiles[hero['name_en']]['base']=hero['base'].copy()
            else:profiles[hero['name_en']]={'name':hero['name_en'],'name_zh':hero['name'],'base':hero['base'].copy(),'archetype':hero.get('archetype','攻击暴击输出'),'sets':[],'main':{},'owned':False}
        for hero in records:
            old=profiles.get(hero['name_en'],{})
            profiles[hero['name_en']]={**old,'name':hero['name_en'],'name_zh':hero['name'],'base':hero['base'].copy(),'archetype':hero['archetype'],'sets':hero.get('sets',old.get('sets',[])),'main':hero.get('main',old.get('main',{})),'owned':old.get('owned',False),'custom_profile':True}
        self.heroes=list(profiles.values())
        if self.picker is not None and self.picker.winfo_exists():
            self.picker.catalog=self.hero_catalog;self.picker.photos.clear();self.picker.filter()
        if hasattr(self,'candidate_sidebar'):self.candidate_sidebar.photos.clear()

    def edit_hero(self,new=False):
        hero=None if new else next((h for h in self.hero_catalog['heroes'] if h['id']==self.selected_hero_id),None)
        if not new and hero is None:
            self.status.set('请先选择要编辑的角色。');self.choose_hero();return
        if hero:
            profile=next((h for h in self.heroes if h['name']==hero['name_en']),{})
            hero={**hero,'archetype':profile.get('archetype',hero.get('archetype','攻击暴击输出')),'sets':hero.get('sets',profile.get('sets',[]))}
        HeroEditor(self,hero,self.save_hero_panel)

    def save_hero_panel(self,record,avatar=None):
        if avatar:
            folder=USER/'hero-portraits';folder.mkdir(parents=True,exist_ok=True)
            path=folder/(record['id']+'.png')
            with Image.open(avatar) as picture:picture.convert('RGBA').save(path)
            record['portrait']=str(path.resolve())
        records={h['id']:h for h in user_heroes(self.custom_hero_path)};records[record['id']]=record
        save_user_heroes(self.custom_hero_path,list(records.values()));self.reload_heroes();self.apply_hero(record)
        self.status.set('已保存角色基础面板；后续角色库更新会保留本地修改。')

    def import_hero_panels(self):
        name=filedialog.askopenfilename(parent=self.details,filetypes=[('角色JSON','*.json')])
        if not name:return
        try:
            count=import_records(name,self.custom_hero_path,self.hero_catalog);selected=self.selected_hero_id;self.reload_heroes()
            hero=next((h for h in self.hero_catalog['heroes'] if h['id']==selected),None)
            if hero:self.apply_hero(hero)
            self.status.set(f'已导入 {count} 个角色面板。')
        except (ValueError,OSError,TypeError) as exc:messagebox.showerror('导入失败',str(exc),parent=self.details)

    def export_hero_panels(self):
        name=filedialog.asksaveasfilename(parent=self.details,initialfile='hero-panels.json',defaultextension='.json',filetypes=[('角色JSON','*.json')])
        if name:
            profiles={h['name']:h for h in self.heroes}
            records=[{**h,'archetype':profiles.get(h['name_en'],{}).get('archetype','攻击暴击输出'),'sets':h.get('sets',profiles.get(h['name_en'],{}).get('sets',[]))} for h in self.hero_catalog['heroes']]
            Path(name).write_text(json.dumps({'schema':1,'heroes':records},ensure_ascii=False,indent=2),encoding='utf-8');self.status.set('已导出全部角色基础面板，可编辑后重新导入。')

    def apply_hero(self,hero):
        self._changing_base=True
        try:
            for key,var in self.base.items():var.set(str(hero['base'][key]))
        finally:self._changing_base=False
        self.selected_hero_id=hero['id'];self._show_selected_hero(hero)
        if hasattr(self,'character_bs_label'):self.character_bs_label.configure(text='角色 BS — · 尚未读取当前面板')
        bs_window=getattr(self,'character_bs_window',None)
        if bs_window is not None and bs_window.winfo_exists():bs_window.set_hero(hero)
        self.calculate();self._save_preferences()
        self.status.set('已选择 '+hero['name']+'：基础攻击'+str(hero['base']['atk'])+'，生命'+str(hero['base']['hp'])+'，防御'+str(hero['base']['def'])+'。已重新计分。')

    def _show_selected_hero(self,hero):
        with Image.open(ROOT/'data'/hero['portrait']) as source:
            picture=source.convert('RGBA');picture.thumbnail((48,48),Image.Resampling.LANCZOS)
            self.hero_photo=ImageTk.PhotoImage(picture.resize((26,26)),master=self)
        self.hero_display.configure(text=hero['name']+' · 60级满觉醒',image=self.hero_photo,compound='left')

    def _base_edited(self,*_):
        if self._changing_base:return
        self.selected_hero_id=None;self.hero_display.configure(text='基础：自定义参考值',image='')
        job=getattr(self,'_calc_job',None)
        if job:self.after_cancel(job)
        self._calc_job=self.after(350,self._calculate_edited)

    def _pair(self,parent,label,variable,values=None):
        ttk.Label(parent,text=label,foreground=MUTED).pack(anchor='w',pady=(3,4))
        widget=ttk.Combobox(parent,textvariable=variable,values=values) if values else ttk.Entry(parent,textvariable=variable)
        widget.pack(fill='x');return widget

    def _mini(self,parent,label,variable,values=None,width=14):
        frame=ttk.Frame(parent,style='Card.TFrame');frame.pack(side='left',fill='x',expand=True,padx=(0,7))
        ttk.Label(frame,text=label,foreground=MUTED).pack(anchor='w',pady=(0,3))
        widget=ttk.Combobox(frame,textvariable=variable,values=values,state='readonly',width=width) if values else ttk.Entry(frame,textvariable=variable,width=width)
        widget.pack(fill='x')

    def _stat_row(self,parent,key,value):
        row=ttk.Frame(parent,style='Card.TFrame');row.pack(fill='x',pady=1)
        ttk.Combobox(row,textvariable=key,values=['']+list(LABELS.values()),state='readonly',width=17).pack(side='left',fill='x',expand=True,padx=(0,8))
        ttk.Entry(row,textvariable=value,width=10).pack(side='left')

    def _form_changed(self,*_):
        if not self.updating:
            self.reforge_after=None
            self.origin='手动校正';self.verified.set(False)
            pending=getattr(self,'_calc_job',None)
            if pending:self.after_cancel(pending)
            self._calc_job=self.after(350,self._calculate_edited)

    def _calculate_edited(self):
        self._calc_job=None;self.calculate()

    def get_gear(self):
        reverse={v:k for k,v in LABELS.items()}
        def stat(k,v):
            if not k.get() and not v.get().strip():return None
            if not k.get() or not v.get().strip():raise ValueError('词条类型和数值需同时填写')
            return Stat(reverse[k.get()],float(v.get().strip().rstrip('%')))
        props={k:v.get().strip() for k,v in self.vars.items()}
        for k in ['level','enhance']:props[k]=int(props[k]) if props[k] else None
        props['screen_score']=float(props['screen_score']) if props['screen_score'] else None
        props['main']=stat(self.main_key,self.main_value)
        props['subs']=[s for s in (stat(k,v) for k,v in zip(self.sub_keys,self.sub_values)) if s]
        return Gear(**props)

    def fill_gear(self,gear,origin='OCR读取'):
        self.reforge_after=None
        self.updating=True
        try:
            for k,v in self.vars.items():
                value=getattr(gear,k);v.set('' if value is None else str(value))
            self.main_key.set(LABELS.get(gear.main.key,'') if gear.main else '');self.main_value.set(f'{gear.main.value:g}' if gear.main else '')
            for i,(k,v) in enumerate(zip(self.sub_keys,self.sub_values)):
                s=gear.subs[i] if i<len(gear.subs) else None;k.set(LABELS[s.key] if s else '');v.set(f'{s.value:g}' if s else '')
        finally:self.updating=False
        self._quality_from_gear(gear)
        self.origin=origin;self.verified.set(False)

    def calculate(self):
        try:
            gear=self.get_gear();mode=self.score_mode.get()
            base={k:float(v.get()) for k,v in self.base.items()}
            result=evaluate_advice(gear,base,self.route.get(),self.reforged.get(),self.fixed_main.get(),mode)
            import scoring_settings
            self.score_caption.configure(text='装备总分 · Fribbels（单件）' if mode=='gs' else scoring_settings.current()['name'] if mode=='custom' else 'Fribbels 角色换算')
            self.last_gs=sum(x['score'] for x in breakdown(gear,score_mode='gs'))
            color=GREEN if result['kind'] in {'enhance','reforge','excellent'} else RED
            self.score_value.configure(foreground=color);self.gs_score.configure(text=f'标准GS分 {self.last_gs:.2f}',foreground=color)
            self.last_gear=gear;self.last_decision=result
            short={'reforge':'建议重铸','discard':'建议分解','backup':'停止强化 · 替补','usable':'保留使用','excellent':'优先保留'}
            title=f'强化到 +{result["next_stage"]}' if result['kind']=='enhance' and result.get('next_stage') else short.get(result['kind'],result['title'])
            if result.get('blocked_fixed_main'):title='不推荐强化'
            self.verdict.configure(text=title,foreground=RED if result['kind']=='discard' else GREEN if result['kind'] in {'enhance','reforge','excellent'} else GOLD)
            screen=f'{gear.screen_score:g}' if gear.screen_score is not None else '未读到'
            level=f'{gear.level}' if gear.level is not None else '未读到'
            stage=f'+{gear.enhance}' if gear.enhance is not None else '未读到'
            from fribbels_gs import item_score
            self.score_value.configure(text=(str(item_score(gear)) if mode=='gs' else f'{result["score"]:.2f}') if result['breakdown'] else '—')
            self.scores.configure(text=f'{stage} · {self.quality_choice.get()} · 原始分 {result["score"]:.3f} · 官方{screen}')
            self.threshold_label.configure(text=result.get('threshold_text','当前门槛 —').replace('当前门槛','门槛'))
            notice=recognition_notice(gear);self.recognition_label.configure(text=notice)
            if notice:self.recognition_label.pack(fill='x',pady=(4,0))
            else:self.recognition_label.pack_forget()
            reasons=list(result['reasons'])
            if result['errors']:reasons.append('得分仅按已读副属性计算；信息不完整时不给处置结论。')
            import advice_templates
            custom_note=advice_templates.text(result['kind'])
            if custom_note:reasons.insert(0,'自定义说明：'+custom_note)
            self.reason.configure(text='\n'.join(reasons if result.get('conditional') else reasons[:2]),font=(FONT,9))
            lines=['当前计分：'+('Fribbels GS（界面按单件四舍五入，强化门槛仍比较未取整原值）' if mode=='gs' else scoring_settings.current()['name']+'（自定义公式）' if mode=='custom' else '按角色基础值换算'),f'本次路线：{result["route"]}']
            for x in result['breakdown']:lines.append(f'{LABELS[x["key"]]}：{x["formula"]} = {x["score"]:.3f}分')
            lines.append(f'合计：{result["score"]:.3f}分（比较门槛前不取整）')
            if gear.enhance and self.route.get()==ROUTES[0]:lines.append('自动路线按当前状态推断，无法还原此前是否在追速；可在“更多设置”指定。')
            lines.extend(['',*result['reasons']])
            if mode=='role':lines.append('\n角色基础：攻击'+str(base['atk'])+' / 生命'+str(base['hp'])+' / 防御'+str(base['def']))
            else:lines.append('\n标准GS使用固定系数，完全不使用角色基础数值。')
            self._write(self.comparison,'\n'.join(lines))
            self.roles.delete(*self.roles.get_children())
            all_rows=candidate_rows(gear,self.heroes,self.hero_catalog,base,mode,limit=None) if gear.subs else []
            effective_details=''
            selected=next((r for r in all_rows if r.get('hero') and r['hero']['id']==self.selected_hero_id),None)
            if not self.selected_hero_id:self.hero_effective.configure(text='当前角色有效分：请先选角色',foreground=color);self.selected_effective=None
            elif selected is None:self.hero_effective.configure(text='当前角色有效分：暂无词条需求资料',foreground=GOLD);self.selected_effective=None
            else:
                weights=selected.get('weights',{});effective=sum(p['score']*weights.get(p['key'],0) for p in result['breakdown']);self.selected_effective=effective
                basis=selected.get('demand_basis','资料不足');basis='导入需求档案' if '导入' in basis else '配装统计参考' if 'Fribbels' in basis else '模板参考' if basis=='玩法模板' else '角色档案参考'
                self.hero_effective.configure(text=f'当前角色有效分：{effective:.2f} · {basis}',foreground=color)
                effective_lines=[f"{LABELS[p['key']]} {p['score']:.2f} × {weights.get(p['key'],0):g} = {p['score']*weights.get(p['key'],0):.2f}" for p in result['breakdown']]
                effective_details=f'当前角色有效分 {effective:.2f}（{basis}）\n'+'\n'.join(effective_lines)
                self._write(self.comparison,self.comparison.get('1.0','end')+'\n当前所选角色有效分：'+f'{effective:.2f}（{basis}）\n'+'\n'.join(effective_lines))
            rows=all_rows[:25]
            self._candidate_rows=rows
            self.candidate_sidebar.update_rows(rows)
            for row in rows:self.roles.insert('','end',image=self.candidate_sidebar.photos.get(row['hero']['id'],'') if row.get('hero') else '',values=(row['display_name'],row['archetype'],row['effective']))
            self.render_summary(gear,result,base)
            if effective_details:self.main_calculations.configure(text=self.main_calculations.cget('text')+'\n\n'+effective_details)
            after=getattr(self,'reforge_after',None);self.show_reforge_changes(gear,after)
            if after:
                role_after=sum(x['score'] for x in breakdown(after,base,mode));gs_after=sum(x['score'] for x in breakdown(after,score_mode='gs'))
                official=f'{gear.screen_score:g} → {after.screen_score:g}' if gear.screen_score is not None and after.screen_score is not None else '未读全'
                text=f'重铸预览 · {gear.name or gear.slot or "装备"}\n'+('GS' if mode=='gs' else '角色分')+f' {result["score"]:.2f} → {role_after:.2f}（+{role_after-result["score"]:.2f}）\n官方分 {official}'
                self.reason.configure(text=text,font=(FONT,12,'bold'));self.main_calculations.configure(text=self.main_calculations.cget('text')+'\n\n'+text+'\n'+'\n'.join(f'{LABELS[a.key]}：{a.value:g} → {b.value:g}' for a,b in zip(gear.subs,after.subs)))
                self._write(self.comparison,self.comparison.get('1.0','end')+'\n\n'+text);self.request_result_fit()
            return gear,result
        except (ValueError,TypeError,KeyError) as exc:
            self.last_gear=None;self.last_decision=None;self.score_value.configure(text='—')
            self.verdict.configure(text='尚无有效数值',foreground=GOLD);self.reason.configure(text=str(exc));self._write(self.comparison,str(exc));self.status.set(str(exc));return None,None

    def read_screen(self,mode='single'):
        if self.busy:return
        try:
            if self.auto_window.get():
                windows=find_game_windows();selection=None
                if len(windows)>1:
                    lines=['发现多个游戏窗口，请输入序号：']+[f'{i+1}. {w["title"]} {w["rect"]}' for i,w in enumerate(windows)]
                    index=simpledialog.askinteger('选择游戏窗口','\n'.join(lines),minvalue=1,maxvalue=len(windows),parent=self)
                    if index is None:return
                    selection=index-1
                region=select_game_rectangle(windows,selection)
            else:
                if not self.region:raise ValueError('请先手动框选完整游戏窗口，或开启自动定位')
                region=self.region[:]
            request={'mode':mode,'slot':self.craft_window.slot.get() if mode=='batch' and hasattr(self,'craft_window') else self.vars['slot'].get()}
            if self.auto_window.get():request['window']=windows[selection if selection is not None else 0]
            else:request['rect']=region
            if 'rect' in request and mode=='batch' and hasattr(self,'craft_window') and self.craft_window.winfo_exists():
                board=self.craft_window;bx,by=board.winfo_rootx(),board.winfo_rooty()
                overlap=bx<region[2] and by<region[3] and bx+board.winfo_width()>region[0] and by+board.winfo_height()>region[1]
                if board.state()=='normal' and overlap:board.withdraw();self._restore_craft_after_capture=True
            self.start_scan(request)
        except ValueError as exc:self.status.set(str(exc));self.stop_live()

    def pick_region(self):
        self.stop_live()
        def selected(rect):self.region=rect;self.auto_window.set(False);self.status.set(f'已手动选择 {rect}。请保持窗口位置，点击读取并计算。');self._save_preferences()
        RegionSelector(self,selected)

    def open_image(self):
        filename=filedialog.askopenfilename(filetypes=[('游戏装备截图','*.png *.jpg *.jpeg *.bmp')])
        if filename:self.stop_live();self.start_scan({'path':str(Path(filename).resolve())})

    def open_craft(self,preserve_live=False):
        if not preserve_live and not self.craft_live:self.stop_live()
        if not hasattr(self,'craft_window') or not self.craft_window.winfo_exists():self.craft_window=CraftWindow(self)
        if not preserve_live:self.craft_window.deiconify();self.craft_window.lift()

    def open_craft_image(self):
        self.stop_live()
        self.open_craft()
        filename=filedialog.askopenfilename(parent=self.craft_window,filetypes=[('装备制作截图','*.png *.jpg *.jpeg *.bmp')])
        if filename:self.start_scan({'path':str(Path(filename).resolve()),'mode':'batch','slot':self.craft_window.slot.get()})

    def ensure_ocr(self):
        if self.ocr is None:
            from cloud_ocr import PROVIDERS,CloudOCR,load_profiles
            if self.active_engine in PROVIDERS:
                provider=PROVIDERS[self.active_engine];self.ocr=CloudOCR(provider,load_profiles(self.cloud_ocr_path)[provider])
            else:self.ocr=WindowsOCR() if self.active_engine=='Windows OCR' else LocalOCR()
        return self.ocr

    def ensure_reader(self):
        if self.active_engine=='视觉模型 API':
            from recognition_engine import VisionScreenReader
            if not isinstance(getattr(self,'reader',None),VisionScreenReader):self.reader=VisionScreenReader(self.vision_path)
            return self.reader
        ocr=self.ensure_ocr()
        if not hasattr(self,'reader') or self.reader.ocr is not ocr:self.reader=ScreenReader(ocr)
        self.reader.catalog=self.hero_catalog
        return self.reader

    def start_scan(self,request):
        if self.busy:return
        self.active_mode=request.get('mode','single')
        self.busy=True;token=self.sequence
        self.status.set('正在读取当前画面并按上游算法计算，请保持强化面板静止…')
        # Capture only the game window; the tool remains visible.
        def run():
            try:
                if request.get('window'):
                    import tempfile
                    from window_capture import capture_game_window
                    with tempfile.TemporaryDirectory(prefix='e7-panel-') as directory:
                        path=Path(directory)/'panel.png';capture_game_window(request['window']).save(path)
                        value=self.ensure_reader().read({'path':str(path),'character_read':request.get('character_read',False),'hero_id':request.get('hero_id')},mode=request.get('mode','single'),slot=request.get('slot',''),on_captured=lambda:self.pending.put(('captured',token,None)))
                else:
                    value=self.ensure_reader().read(request,mode=request.get('mode','single'),slot=request.get('slot',''),on_captured=lambda:self.pending.put(('captured',token,None)))
                self.pending.put(('result',token,value))
            except Exception as exc:self.pending.put(('error',token,str(exc)))
        self.after(80,lambda:threading.Thread(target=run,daemon=True).start())

    def show_after_capture(self):
        if self.hidden_for_capture:self.hidden_for_capture=False;self.deiconify();self.lift()
        if getattr(self,'_restore_craft_after_capture',False):
            self._restore_craft_after_capture=False
            if hasattr(self,'craft_window') and self.craft_window.winfo_exists():self.craft_window.deiconify();self.craft_window.lift()

    def poll(self):
        try:
            while True:
                kind,token,value=self.pending.get_nowait()
                if kind=='captured':self.show_after_capture();continue
                self.busy=False;self.show_after_capture()
                if kind=='languages':
                    self.status.set('可用OCR语言：'+', '.join(value)+'。' + ('已具备中文OCR。' if any(v.startswith('zh') for v in value) else '请在Windows语言选项中安装简体中文OCR。'));continue
                if token!=self.sequence:continue
                if kind=='error':
                    if value.startswith('云OCR'):
                        self.stop_live();self.status.set(value);continue
                    if getattr(self,'active_mode','single')=='batch':
                        if self.craft_live:
                            self.status.set('连续读取中 · 等待制作完毕界面，保留上次结果')
                            self.after(900,lambda t=token:self.read_screen('batch') if self.craft_live and self.sequence==t else None);continue
                        self.stop_craft_live();self.status.set('装备制作识别失败：'+value[:180]);continue
                    self.score_value.configure(text='—');self.scores.configure(text='本次读取失败');self.reason.configure(text='请重新读取或手动填写。')
                    self.stop_live();self.status.set('读取失败：'+value[:210]);self.verdict.configure(text='本次未读到可靠属性',foreground=GOLD)
                    if self.ocr:self.ocr.close();self.ocr=None
                elif kind=='result':
                    self.accept_result(value)
                    if self.live:
                        self.after(500,lambda t=token:self.read_screen() if self.live and self.sequence==t else None)
                    elif self.craft_live:
                        self.after(900,lambda t=token:self.read_screen('batch') if self.craft_live and self.sequence==t else None)
        except queue.Empty:pass
        self.after(100,self.poll)

    def accept_result(self,value):
        if value.get('kind')=='character_metadata':self.accept_character_metadata(value);self._write(self.raw,value.get('text',''));return
        if value.get('kind')=='character':self.accept_character(value);self._write(self.raw,value.get('text',''));return
        if value.get('kind')=='batch':
            self.open_craft(preserve_live=True);self.craft_window.set_entries(value['entries']);self.status.set(('连续读取中 · ' if self.craft_live else '')+f'共{len(value["entries"])}件'+(' · 画面未变，已复用结果' if value.get('cache_hit') else ' · 已更新留存建议'));return
        gear=value['gear'];self.fill_gear(gear);self.reforge_after=Gear.from_dict(value['reforge_after']) if value.get('reforge_after') else None;self._write(self.raw,value.get('text',''));self.calculate()
        if value.get('preview_png'):
            self.last_preview=value['preview_png'];photo=tk.PhotoImage(data=self.last_preview)
            scale=max(1,(photo.width()+499)//500,(photo.height()+449)//450)
            self.photo=photo.subsample(scale,scale);self.preview.configure(image=self.photo,text='')
        self.status.set('已读取重铸预览的前后两列，尚未执行重铸。' if value.get('layout')=='reforge-preview' else '已读取角色页装备弹窗。' if value.get('layout')=='hero-equipment-popup' else '已读取背包右侧详情。' if value.get('layout')=='inventory-right' else '已读取装备；可继续强化后再次读取。')

    def check_ocr(self):
        if self.busy:return
        self.busy=True;token=self.sequence
        def run():
            try:self.pending.put(('languages',token,self.ensure_ocr().request(action='languages')['languages']))
            except Exception as exc:self.pending.put(('error',token,str(exc)))
        threading.Thread(target=run,daemon=True).start()

    def toggle_live(self):
        if self.live:self.stop_live();self.status.set('已停止连续读取装备。');return
        self.stop_craft_live();self.live=True;self.live_button.configure(text='停止连续读取 F9');self.read_when_idle('single',self.sequence)

    def read_when_idle(self,mode,token):
        active=self.craft_live if mode=='batch' else self.live
        if not active or token!=self.sequence:return
        if self.busy:self.after(120,lambda:self.read_when_idle(mode,token))
        else:self.read_screen(mode)

    def stop_live(self):
        self.live=False;self.sequence+=1;self.live_button.configure(text='连续读取装备 F9');self.stop_craft_live(invalidate=False)

    def toggle_craft_live(self):
        if self.craft_live:
            self.stop_craft_live();self.status.set('已停止装备制作连续读取。');return
        self.stop_live();self.open_craft(preserve_live=True);self.craft_live=True
        self.craft_window.live_button.configure(text='停止连续读取 F9');self.read_when_idle('batch',self.sequence)

    def stop_craft_live(self,invalidate=True):
        was=getattr(self,'craft_live',False);self.craft_live=False
        if was and invalidate:self.sequence+=1
        if hasattr(self,'craft_window') and self.craft_window.winfo_exists():self.craft_window.live_button.configure(text='连续读取 F9')

    def new_item(self):
        self.stop_live();self.item_id=None;self.last_gear=None;self.last_decision=None
        pending=getattr(self,'_calc_job',None)
        if pending:self.after_cancel(pending);self._calc_job=None
        self.fill_gear(Gear(),origin='等待读取');self.quality_choice.set('未识别')
        self.show_reforge_changes(Gear(),None)
        self.route.set(ROUTES[0]);self.verified.set(False);self.history_var.set('')
        self.threshold_label.configure(text='当前门槛 —');self.recognition_label.configure(text='')
        self.hero_effective.configure(text='当前角色有效分：读取装备后计算');self.selected_effective=None
        self.score_value.configure(text='—');self.gs_score.configure(text='标准GS分 —');self.main_calculations.configure(text='读取后显示计算明细');self.verdict.configure(text='读取下一件装备',foreground=GOLD)
        self.scores.configure(text='强化 —   ·   官方分 —');self.reason.configure(text='角色与基础属性保持不变。')
        for label in self.stat_points:label.configure(text='— 分')
        self._write(self.history_text,'新装备尚无基线，核对后再记录。');self.status.set('已清空上一件装备，点击读取装备。')

    def record(self):
        self.stop_live();gear,result=self.calculate()
        if not gear or result['errors']:return
        if not self.verified.get():messagebox.showinfo('请先核对','保存强化历史前，请核对读数并勾选“我已核对当前读数”。');return
        try:
            if self.item_id is None:self.item_id=self.db.create_item(gear.name or f'{gear.set_name}{gear.slot}')
            event=self.db.record(self.item_id,gear);self.refresh_history_selector();self.show_history()
            self.status.set('已记录当前节点；强化后再次读取并记录。' if event else '与上一条相同，未重复保存。')
        except ValueError as exc:messagebox.showerror('本次变化未记录',str(exc))

    def refresh_history_selector(self):
        self.history_ids={f'#{i}  {label}':i for i,label,_ in self.db.list_items()};self.history_selector['values']=list(self.history_ids)
        for label,item in self.history_ids.items():
            if item==self.item_id:self.history_var.set(label)

    def load_history_item(self,event=None):
        self.stop_live();self.item_id=self.history_ids.get(self.history_var.get());rows=self.db.observations(self.item_id)
        if rows:self.fill_gear(Gear.from_dict(rows[-1]['gear']),origin='历史读数');self.verified.set(True);self.calculate()
        self.show_history()

    def show_history(self):
        lines=[]
        for row in self.db.observations(self.item_id):
            g=row['gear'];event=row['event'];lines.append(f'{row["created"]} · +{g["enhance"]} · 画面分 {g.get("screen_score")}')
            if not event:lines.append('起始基线；此前跳值未知。')
            else:
                lines.append(event['note'])
                for c in event['changes']:lines.append(f'{LABELS[c["key"]]}：{c["before"] if c["before"] is not None else "新增"} → {c["after"]:g}（+{c["delta"]:g}）')
                if event.get('steps')==1 and len(event['changes'])==1:
                    c=event['changes'][0]
                    lines.append(describe_roll(g['level'],g['grade'],c['key'],c['delta'],self.roll_profile.get()))
                m=event.get('main_change')
                if m and m['delta']:lines.append(f'主属性成长另列：{m["before"]:g} → {m["after"]:g}（+{m["delta"]:g}）')
            lines.append('')
        self._write(self.history_text,'\n'.join(lines) or '暂无记录。')

    def export_history(self):
        filename=filedialog.asksaveasfilename(defaultextension='.json',initialfile='e7-pc-enhancement-history.json')
        if filename:self.db.export(filename);self.status.set('记录已导出。')

    def _load_preferences(self):
        try:
            settings=json.loads((USER/'pc-settings.json').read_text(encoding='utf-8'))
            for k,v in self.base.items():v.set(str(settings.get('base',{}).get(k,ALL_BASE_DEFAULTS[k])))
            hero=next((h for h in self.hero_catalog['heroes'] if h['id']==settings.get('selected_hero_id')),None)
            if hero:
                for k in self.base:
                    if k not in settings.get('base',{}):self.base[k].set(str(hero['base'][k]))
            if hero and all(float(self.base[k].get())==hero['base'][k] for k in self.base):self.selected_hero_id=hero['id'];self._show_selected_hero(hero)
            from algorithm_modes import migrate_mode
            import scoring_settings
            self.score_mode.set(migrate_mode(settings,scoring_settings.enabled()))
            self.region=settings.get('region');self.auto_window.set(bool(settings.get('auto_window',True)));self.roll_profile.set(settings.get('roll_profile',PROFILES[0]))
            label=settings.get('input_mode')
            if label in emulator.INPUT_MODES:self.input_mode.set(label)
        except (OSError,ValueError,TypeError):pass
        emulator.DEFAULT_INPUT=emulator.INPUT_MODES.get(self.input_mode.get(),'auto')

    def _save_preferences(self):
        (USER/'pc-settings.json').write_text(json.dumps({'base':{k:v.get() for k,v in self.base.items()},'region':self.region,'auto_window':self.auto_window.get(),'input_mode':self.input_mode.get(),'roll_profile':self.roll_profile.get(),'selected_hero_id':self.selected_hero_id,'score_mode':self.score_mode.get(),'score_mode_schema':2},ensure_ascii=False,indent=2),encoding='utf-8')

    def input_mode_changed(self):
        emulator.DEFAULT_INPUT=emulator.INPUT_MODES.get(self.input_mode.get(),'auto')
        self._save_preferences()

    def detect_emulator(self):
        """Report which window hosts the game and how clicks would reach it."""
        emulator.DEFAULT_INPUT=emulator.INPUT_MODES.get(self.input_mode.get(),'auto')
        try:
            windows=find_game_windows()
        except (OSError,RuntimeError) as exc:
            self.input_status.configure(text='检测失败：'+str(exc));return
        if not windows:
            self.input_status.configure(text='没有找到游戏窗口：请打开第七史诗（PC 客户端或模拟器）。');return
        window=windows[0]
        source='模拟器 · '+window['emulator'] if window.get('source')=='emulator' else 'PC 客户端'
        backend=None;note=''
        if window.get('source')=='emulator':
            try:
                backend=emulator.open_input(window,backend=emulator.DEFAULT_INPUT)
                if backend is None:note='未启用模拟器输入（将尝试窗口消息）'
                else:
                    width,height=backend.size
                    note=f'{type(backend).__name__} · 设备 {width}×{height} · 点击不抢鼠标'
                    backend.close()
            except (OSError,RuntimeError) as exc:
                note='输入不可用：'+str(exc)
        detail=window.get('client') or [0,0]
        self.input_status.configure(text=f"当前窗口：{source} · {window['title']} · 客户区 {detail[0]}×{detail[1]}"+(f' · {note}' if note else ''))
        self.status.set(self.input_status.cget('text'))

    def algorithm_notes(self):
        from threshold_settings import current
        mode=self.score_mode.get();c=current(mode);left,right,speed=c['left'],c['right'],c['speed']
        lines=['Fribbels 角色换算：暴击×1.6；暴伤×8/7；速度×2；其他百分比×1。',
               '固定攻击／生命／防御：数值÷所选角色对应基础属性×100。仅累加副属性，主属性不计分。',
               '', '左三件＝武器、头盔、铠甲；右三件＝项链、戒指、鞋子。',
               '蓝装一律分解；右三件固定攻、防、生命主属性不推荐强化。', '']
        for title,values in [('左三件',left),('右三件',right)]:
            lines.append(f'{title}：未强化紫装{values["purple"]:g}分／红装{values["red"]:g}分 → 强化至+6。')
            lines.append('；'.join(f'+{k}门槛{values[k]:g}分' for k in ('6','9','12','15'))+f'；重铸后{values["90"]:g}分优秀。')
        lines.extend(['',f'左三件追速：初始≥{speed["entry"]:g}速 → +6/+9检查≥{speed["6"]:g}速 → +12检查≥{speed["12"]:g}速。',
                     f'+12未达速度线：达到{left["12"]:g}分进入+15；达到{speed["usable_score"]:g}分保留使用，否则替补。',
                     f'+15≥{speed["15"]:g}速考虑重铸；重铸后≥{speed["90"]:g}速优秀。',
                     '右三件不使用左侧初始追速例外。85级达标才建议重铸；88级不能自动视为90级。',
                     '不单列+3判断节点，不叠加强化等级分，不增加分数容差。',
                     '', '角色有效分：副属性换算分×该英雄词条需求权重。Fribbels统计、个人JSON配置和模板会标明来源。',
                     '角色适配与有效分只评价当前单件装备。'])
        import scoring_settings
        if mode=='custom':lines[0:2]=['当前算法：'+scoring_settings.current()['name']+'（自定义）。仅累加副属性。','；'.join(LABELS[k]+'：'+v for k,v in scoring_settings.current()['formulas'].items()),'更换算法后请检查左／右三件门槛是否合适。']
        if mode=='gs':lines[0:2]=['Fribbels 装备 GS：固定攻/生/防使用 ItemDb 系数；暴击×1.6，暴伤×8/7，速度×2。','单件展示四舍五入；门槛比较原始分。主属性不计入副属性 GS。']
        return '\n'.join(lines)

    def close(self):
        task_window=getattr(self,'task_replay_window',None)
        if task_window is not None and task_window.winfo_exists():task_window.close()
        self.game_window_controls.close_preview()
        self.sync_cancel.set()
        if hasattr(self,'reader') and hasattr(self.reader,'close'):self.reader.close()
        self._save_preferences()
        if self.ocr:self.ocr.close()
        # Cancel through the widget that registered the callback. Using the root
        # for a child callback leaves a stale Tcl command in that child's list.
        owners={}
        def collect(widget):
            for command in widget._tclCommands or ():owners[command]=widget
            for child in widget.winfo_children():collect(child)
        collect(self)
        for task in self.tk.splitlist(self.tk.call('after','info')):
            try:
                script=self.tk.call('after','info',task)[0]
                command=self.tk.splitlist(script)[0]
                owners.get(command,self).after_cancel(task)
            except (tk.TclError,IndexError):pass
        self.db.close();self.destroy()


def main():
    if os.name=='nt':
        try:ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError,OSError):ctypes.windll.user32.SetProcessDPIAware()
    PCCalculator().mainloop()


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        USER.mkdir(parents=True,exist_ok=True);details=traceback.format_exc();(USER/'pc-startup-error.log').write_text(details,encoding='utf-8')
        if os.name=='nt':ctypes.windll.user32.MessageBoxW(None,'启动失败，请查看userdata/pc-startup-error.log\n'+details[-500:],'PC装备计算器',16)
        else:raise
