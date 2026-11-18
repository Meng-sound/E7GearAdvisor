"""Data updates, engine settings and character summary integrations."""
import json,queue,threading,copy,tkinter as tk
from pathlib import Path
from tkinter import ttk,filedialog,messagebox
import adaptation_storage,threshold_settings
from build_reference import references,configure_cache,enrich_profiles
from core import Gear,ARCHETYPES,LABELS,SLOTS
from hero_storage import user_heroes,save_user_heroes
from character_reader import find_hero
from cloud_ocr import PROVIDERS
ENGINES=('本地 PP-OCRv4','Windows OCR',*PROVIDERS,'视觉模型 API')

class FeatureMixin:
 def check_software_update(self):
  window=self.open_software_update()
  window.after_idle(window.check)
  return window

 def open_software_update(self):
  from software_update_ui import open_update
  return open_update(self)

 def open_character_bs(self):
  from character_bs_ui import open_bs
  return open_bs(self)

 def open_selected_reference(self):
  hero=next((h for h in self.hero_catalog['heroes'] if h['id']==self.selected_hero_id),None)
  if hero:
   from reference_window import show_reference
   return show_reference(self,hero)
  self.choose_hero();self.status.set('先选择角色，再点击顶部角色参考。')

 def open_threshold_config(self):
  return threshold_settings.open_editor(self,self.threshold_path,self.thresholds_changed,self.score_mode.get())


 def open_optimizer_interface(self):
  from optimizer_interface import open_interface
  return open_interface(self)

 def init_extensions(self,user):
  self.user_dir=Path(user);self.engine_path=self.user_dir/'recognition-settings.json';self.vision_path=self.user_dir/'vision-api.json';self.threshold_path=self.user_dir/'strengthening-gates.json';self.base_cache_path=self.user_dir/'synced-hero-panels.json'
  self.data_tasks=queue.Queue();self.sync_cancel=threading.Event();self.sync_active=False
  try:config=json.loads(self.engine_path.read_text(encoding='utf8'))
  except (OSError,ValueError):config={}
  self.engine_choice=tk.StringVar(value=config.get('engine','本地 PP-OCRv4'))
  if self.engine_choice.get() not in ENGINES:self.engine_choice.set('本地 PP-OCRv4')
  self.active_engine=self.engine_choice.get();self.cloud_ocr_path=self.user_dir/'cloud-ocr.json'
  import local_json,advice_templates
  self.import_settings_path=self.user_dir/'import-settings.json';self.advice_templates_path=self.user_dir/'advice-templates.json'
  for module,path in ((local_json,self.import_settings_path),(advice_templates,self.advice_templates_path)):
   try:module.configure(path)
   except (ValueError,OSError):pass
  self.scoring_path=self.user_dir/'custom-scoring.json';self.algorithm_load_error=''
  import scoring_settings
  try:scoring_settings.configure(self.scoring_path)
  except (OSError,ValueError) as e:self.algorithm_load_error=str(e)
  try:threshold_settings.configure(self.threshold_path)
  except (OSError,ValueError):pass

 def add_feature_controls(self,settings,roles_tab,banner):
  ttk.Button(banner,text='关于',style='Compact.TButton',command=self.show_sources).pack(side='right',padx=8)
  extra=ttk.Frame(settings);extra.pack(fill='x',pady=5)
  ttk.Button(extra,text='自定义建议说明',command=self.open_advice_templates).pack(side='left',padx=(0,8))
  ttk.Button(extra,text='JSON 导入上限',command=self.open_import_settings).pack(side='left')
  ttk.Button(settings,text='软件更新',command=self.open_software_update).pack(anchor='w',pady=5)
  scoring_row=ttk.Frame(settings);scoring_row.pack(fill='x',pady=5)
  ttk.Button(scoring_row,text='分数与速度门槛',command=self.open_threshold_config).pack(side='left',padx=(0,8))
  ttk.Button(scoring_row,text='自定义算分算法',command=self.open_scoring_config).pack(side='left')
  engines=ttk.Frame(self.notebook,padding=16,style='Card.TFrame');self.notebook.add(engines,text='识别引擎')
  ttk.Label(engines,text='读取方式',font=('Microsoft YaHei UI',13,'bold')).pack(anchor='w',pady=(0,8))
  ttk.Combobox(engines,textvariable=self.engine_choice,values=ENGINES,state='readonly').pack(fill='x')
  ttk.Label(engines,text='本地OCR不上传截图。视觉API会把本次游戏截图发送到你配置的服务，可能产生费用；模型只提取字段，分数由本地计算。',wraplength=710).pack(anchor='w',pady=12)
  row=ttk.Frame(engines);row.pack(fill='x');ttk.Button(row,text='应用识别引擎',command=self.change_engine).pack(side='left',padx=(0,8));ttk.Button(row,text='视觉模型 API 配置',command=self.open_vision_config).pack(side='left');ttk.Button(row,text='云 OCR 配置',command=self.open_cloud_ocr_config).pack(side='left',padx=8)
  ttk.Label(engines,text='视觉模型擅长复杂布局，但也可能读错数字、百分号和强化增量。无法确认的字段仍需人工校验。',wraplength=710).pack(anchor='w',pady=14)
  updates=ttk.Frame(roles_tab);updates.pack(fill='x',pady=(0,6),before=self.roles)
  self.hero_link=tk.StringVar();ttk.Entry(updates,textvariable=self.hero_link).pack(side='left',fill='x',expand=True,padx=(0,6));ttk.Button(updates,text='读取英雄链接',command=self.sync_hero_link).pack(side='left')
  row=ttk.Frame(roles_tab);row.pack(fill='x',pady=(0,6),before=self.roles)
  ttk.Button(row,text='Fribbels 自动更新',command=self.sync_all_heroes).pack(side='left');ttk.Button(row,text='暂停 / 保存断点',command=self.sync_cancel.set).pack(side='left',padx=6)
  self.sync_missing=tk.BooleanVar(value=True);ttk.Checkbutton(row,text='仅缺失 / 过期（7天）',variable=self.sync_missing).pack(side='left')
  self.sync_progress=ttk.Progressbar(roles_tab,mode='determinate',maximum=1);self.sync_progress.pack(fill='x',pady=(0,6),before=self.roles)
  self._sync_saved_seen=0
  self.sync_message=tk.StringVar(value='粘贴Hero Library英雄链接，或同步角色资料与配装参考。');ttk.Label(roles_tab,textvariable=self.sync_message,wraplength=740).pack(fill='x',pady=(0,6),before=self.roles)

 def change_engine(self):
  if self.busy:messagebox.showinfo('请稍候','当前读取结束后再切换引擎',parent=self.details);return
  if self.engine_choice.get()=='视觉模型 API':
   from vision_api import load_config,validate_config
   try:validate_config(load_config(self.vision_path))
   except (OSError,ValueError) as e:messagebox.showerror('请先配置视觉API',str(e),parent=self.details);return
  if self.engine_choice.get() in PROVIDERS:
   from cloud_ocr import load_profiles,validate_config
   try:
    provider=PROVIDERS[self.engine_choice.get()];validate_config(provider,load_profiles(self.cloud_ocr_path)[provider])
   except (OSError,ValueError) as e:messagebox.showerror('请先配置云OCR',str(e),parent=self.details);return
  self.active_engine=self.engine_choice.get()
  self.stop_live()
  if self.ocr:self.ocr.close();self.ocr=None
  if hasattr(self,'reader') and hasattr(self.reader,'close'):self.reader.close()
  if hasattr(self,'reader'):del self.reader
  self.engine_path.write_text(json.dumps({'engine':self.engine_choice.get()},ensure_ascii=False),encoding='utf8');self.status.set('已切换识别引擎：'+self.engine_choice.get())
 def open_cloud_ocr_config(self):
  from cloud_ocr_ui import open_config
  open_config(self,self.cloud_ocr_path,PROVIDERS.get(self.engine_choice.get()))
 def open_import_settings(self):
  from local_json import open_settings
  return open_settings(self,self.import_settings_path)
 def open_advice_templates(self):
  from advice_templates import open_editor
  return open_editor(self,self.advice_templates_path,self.thresholds_changed)
 def open_scoring_config(self):
  from formula_editor import open_editor
  return open_editor(self,self.scoring_path,self.thresholds_changed)
 def open_vision_config(self):
  from vision_api import open_config
  open_config(self,self.vision_path,lambda:self.status.set('视觉API配置已在本机加密保存；选择该引擎后生效。'))
 def thresholds_changed(self):
  if hasattr(self,'rules_text'):self._write(self.rules_text,self.algorithm_notes())
  self.calculate()
  if hasattr(self,'craft_window') and self.craft_window.winfo_exists():self.craft_window._last_key=None;self.craft_window.refresh_scores()
  self.status.set('已保存自定义门槛，当前装备与制作建议已重新计算。')

 def begin_data_job(self,worker):
  if self.sync_active:self.sync_message.set('已有同步任务进行中，可先取消。');return
  self.sync_active=True;self.sync_cancel.clear();self.sync_message.set('正在读取公开角色数据；旧缓存继续可用…')
  def run():
   try:self.data_tasks.put(('done',worker()))
   except Exception as e:self.data_tasks.put(('error',str(e)[:400]))
  threading.Thread(target=run,daemon=True).start()
 def poll_extensions(self):
  try:
   while True:
    kind,data=self.data_tasks.get_nowait()
    if kind=='progress':
     if isinstance(data,dict):
      self.sync_progress.configure(maximum=max(1,data['total']),value=data['done'])
      wait=f" · 等待{data['wait_seconds']}秒" if data.get('wait_seconds') else ''
      self.sync_message.set(f"{data['done']}/{data['total']} · {data['phase']}{wait} · {data['current']}\n新增{data['saved']} · 未变{data['unchanged']} · 无样本{data['empty']} · 失败{data['failed']} · 待处理{data['remaining']}")
      if data['saved']!=self._sync_saved_seen:
       self._sync_saved_seen=data['saved'];configure_cache(self.user_dir/'hero-library-cache.json');self.refresh_adaptation_status();self.calculate()
     else:self.sync_message.set(data)
     continue
    self.sync_active=False
    if kind=='error':
     configure_cache(self.user_dir/'hero-library-cache.json');self.reload_heroes();self.refresh_adaptation_status();self.calculate();self.sync_message.set('同步未完成，已保留缓存：'+data);continue
    configure_cache(self.user_dir/'hero-library-cache.json');self.reload_heroes();self.refresh_adaptation_status();self.calculate();self.sync_message.set(data)
  except queue.Empty:pass
  self.after(400,self.poll_extensions)
 def sync_base_heroes(self):
  def work():
   names=self.update_base_data();return f'已更新{len(names)}名英雄基础资料，个人基础面板修改保持优先。'
  self.begin_data_job(work)
 def update_base_data(self,names=None):
  from fribbels_sync import refresh_base_cache,to_catalog_record,save_atomic
  raw=refresh_base_cache(self.user_dir/'fribbels-herodata.json');known={h['name_en']:h for h in self.hero_catalog['heroes']};records=[]
  try:previous=json.loads(self.base_cache_path.read_text(encoding='utf8')).get('heroes',[])
  except (OSError,ValueError):previous=[]
  merged={h['id']:h for h in previous}
  for name,record in raw.items():
   if names and name not in names:continue
   h=to_catalog_record(name,record)
   if name in known:h.update(name=known[name]['name'],portrait=known[name]['portrait'],aliases=known[name].get('aliases',[]))
   merged[h['id']]=h;records.append(h)
  save_atomic(self.base_cache_path,{'schema':1,'heroes':list(merged.values())});return [h['name_en'] for h in records]
 def seed_reference_cache(self):
  from fribbels_sync import save_atomic
  path=self.user_dir/'hero-library-cache.json'
  if not path.exists():save_atomic(path,copy.deepcopy(references()))
  return path
 def sync_hero_link(self):
  from fribbels_sync import hero_from_url,fetch_reference,save_atomic
  from urllib.parse import urlsplit,parse_qs
  link=urlsplit(self.hero_link.get().strip())
  if link.scheme=='https' and link.hostname=='fribbels.github.io' and link.path=='/e7/hero-library.html' and not parse_qs(link.query).get('hero',[''])[0].strip():
   self.sync_all_heroes();return
  try:name=hero_from_url(self.hero_link.get())
  except ValueError as e:self.sync_message.set(str(e));return
  def work():
   if name not in {h['name_en'] for h in self.hero_catalog['heroes']}:
    if name not in self.update_base_data([name]):raise ValueError('数据源尚未收录该英雄，请使用新增角色面板')
   path=self.seed_reference_cache();data=json.loads(path.read_text(encoding='utf8'));data['heroes'][name]=fetch_reference(name);save_atomic(path,data);return '已更新 '+name+' 的角色资料与配装参考。'
  self.begin_data_job(work)
 def sync_reference_hero(self,name):
  from resumable_sync import ResumableSync
  self._sync_saved_seen=0
  def work():
   path=self.seed_reference_cache();config=self.user_dir/'e7-sync-config.json'
   sync=ResumableSync(self.user_dir,path,config if config.exists() else None)
   result=sync.run([name],lambda data:self.data_tasks.put(('progress',data)),self.sync_cancel,force=True)
   return ('已更新 '+name+' 的配装参考与装备总分。') if result['saved'] or result['unchanged'] else (result['stopped'] or '本英雄数据未更新，请查看同步记录。')
  self.begin_data_job(work)

 def sync_all_heroes(self):
  from resumable_sync import ResumableSync
  missing=self.sync_missing.get();known=[h['name_en'] for h in self.hero_catalog['heroes']];self._sync_saved_seen=0
  self.sync_progress.configure(maximum=max(1,len(known)),value=0)
  def work():
   try:names=self.update_base_data()
   except (OSError,ValueError):names=known
   path=self.seed_reference_cache();config=self.user_dir/'e7-sync-config.json'
   sync=ResumableSync(self.user_dir,path,config if config.exists() else None)
   result=sync.run(names,lambda data:self.data_tasks.put(('progress',data)),self.sync_cancel,force=not missing)
   return f"本轮完成{result['done']}/{result['total']}名 · 新增{result['saved']} · 未变{result['unchanged']} · 无样本{result['empty']} · 待处理{result['remaining']}。"+(result['stopped'] or '断点已保存，下次只读取缺失或过期英雄。')
  self.begin_data_job(work)

 def accept_character(self,data):
  hero=next((h for h in self.hero_catalog['heroes'] if h['id']==data.get('hero_id')),None) or find_hero(data.get('hero_name',''),self.hero_catalog)
  if hero:
   self.apply_hero(hero);self.last_character_panel=dict(data.get('panel',{}));self.last_character_hero_id=hero['id']
   self.last_character_loadout=data.get('loadout',{})
   window=self.open_character_bs();window.fill_panel(self.last_character_panel);window.fill_loadout(self.last_character_loadout)
   self.status.set('已读取 '+hero['name']+' 面板；核对套装、神器与额外加成后计算 BS。')
  else:self.status.set('未能确定角色，请手动选择')

 def accept_character_metadata(self,data):
  hero=next((h for h in self.hero_catalog['heroes'] if h['id']==data.get('hero_id')),None)
  if not hero:self.status.set('刻印表角色未确定，请重新选择');return
  from hero_imprints import save_profiles
  save_profiles(self.user_dir/'hero-imprints.json',hero,data['imprint_profiles'])
  if self.selected_hero_id!=hero['id']:self.apply_hero(hero)
  window=self.open_character_bs();window.refresh_imprints()
  window._filling=True;window.imprint_mode.set('待确认');window.imprint_rank.set('');window._filling=False;window.apply_imprint()
  window.imprint_status.set('已读取两种刻印等级表；请核对表格，再选择当前启用类型和等级。')
  self.status.set('已读取 '+hero['name']+' 两种刻印表；没有把表中最高等级当作当前等级。')

 def show_sources(self):
  from source_window import show_sources
  show_sources(self)

 def open_guild_war(self):
  from guild_war_ui import open_guild_war
  return open_guild_war(self)
