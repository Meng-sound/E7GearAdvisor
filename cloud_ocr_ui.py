"""Separate provider credentials and an explicit small-image OCR test."""
import io,queue,threading,tkinter as tk
from tkinter import ttk,messagebox
from PIL import Image,ImageDraw,ImageFont
from ui_theme import BG,CARD,FIELD,TEXT,MUTED,ACCENT,FONT,Card,Button
from cloud_ocr import DEFAULTS,LABELS,Client,load_profiles,save_profiles,validate_config

def open_config(parent,path,selected=None):
 win=tk.Toplevel(parent);win.title('外部 OCR 配置');win.geometry('800x740');win.configure(bg=BG);body=ttk.Frame(win,padding=22);body.pack(fill='both',expand=True)
 ttk.Label(body,text='外部 OCR 服务',font=('Microsoft YaHei UI',17,'bold')).pack(anchor='w',pady=(0,10))
 ttk.Label(body,text='选择云OCR后，当前游戏截图的待识别区域会发送到对应服务，按服务商规则计费。默认仍为本地OCR。密钥仅在本机加密保存。',wraplength=715).pack(anchor='w',pady=(0,12))
 try:profiles=load_profiles(path)
 except (OSError,ValueError):profiles={p:dict(d) for p,d in DEFAULTS.items()}
 notebook=ttk.Notebook(body);notebook.pack(fill='both',expand=True);variables={};tabs={};visibility={}
 for provider,defaults in DEFAULTS.items():
  tab=ttk.Frame(notebook,padding=0);notebook.add(tab,text=LABELS[provider]);tabs[provider]=tab;variables[provider]={};visibility[provider]=[]
  card=Card(tab,height=380);card.pack(fill='both',expand=True,pady=12);inner=card.body
  heading=tk.Frame(inner,bg=CARD);heading.pack(fill='x');tk.Label(heading,text='接口参数',bg=CARD,fg=TEXT,font=(FONT,11,'bold')).pack(side='left');tk.Label(heading,text='AK / SK 加密保存在本机',bg=CARD,fg=MUTED,font=(FONT,8)).pack(side='right')
  endpoint={'volcengine':'https://visual.volcengineapi.com','baidu':'https://aip.baidubce.com/rest/2.0/ocr/v1/','aliyun':'https://ocr-api.<region>.aliyuncs.com'}[provider]
  tk.Label(inner,text='服务地址',bg=CARD,fg=MUTED,font=(FONT,9)).pack(anchor='w',pady=(18,6));tk.Label(inner,text=endpoint,bg=FIELD,fg=TEXT,font=(FONT,10),anchor='w',padx=12,pady=12).pack(fill='x')
  grid=tk.Frame(inner,bg=CARD);grid.pack(fill='x',pady=12);grid.columnconfigure(0,weight=1);grid.columnconfigure(1,weight=1)
  for index,(key,default) in enumerate(defaults.items()):
   label={'access_key':'百度 API Key' if provider=='baidu' else 'AccessKey ID','secret_key':'百度 Secret Key' if provider=='baidu' else 'Secret Access Key / AccessKey Secret','session_token':'STS Session Token（使用长期密钥时留空）','region':'服务区域','mode':'高精度接口类型'}[key]
   cell=tk.Frame(grid,bg=CARD);cell.grid(row=index//2,column=index%2,sticky='ew',padx=(0,14) if index%2==0 else 0,pady=6)
   tk.Label(cell,text=label,bg=CARD,fg=MUTED,font=(FONT,9)).pack(anchor='w',pady=(0,5));var=tk.StringVar(value=profiles[provider].get(key,default));variables[provider][key]=var
   if key=='mode':ttk.Combobox(cell,textvariable=var,values=['accurate','accurate_basic'],state='readonly').pack(fill='x')
   else:
    entry=ttk.Entry(cell,textvariable=var,show='●' if key in ('access_key','secret_key','session_token') else '');entry.pack(fill='x')
    if key in ('access_key','secret_key','session_token'):visibility[provider].append(entry)
  note={'volcengine':'使用火山图像技术OCR的AK/SK；不是方舟视觉大模型的Bearer API Key。接口：OCRNormal。','baidu':'accurate：高精度含位置，适合布局和批量数字识别（推荐）。accurate_basic：高精度版但不返回坐标，布局识别能力受限。需要在百度控制台开通对应接口。','aliyun':'接口：RecognizeAdvanced，默认cn-hangzhou。请在账号中开通文字识别服务并授权此接口；可选STS令牌。'}[provider]
  tk.Label(inner,text=note,bg=CARD,fg=MUTED,font=(FONT,9),wraplength=665,justify='left').pack(anchor='w',pady=12)
  shown=tk.BooleanVar(value=False)
  def toggle(p=provider,v=shown):
   for entry in visibility[p]:entry.configure(show='' if v.get() else '●')
  ttk.Checkbutton(tab,text='显示密钥',variable=shown,command=toggle).pack(anchor='e',pady=(0,4))
 if selected in tabs:notebook.select(tabs[selected])
 status=tk.StringVar(value='尚未测试连接。测试只发送程序生成的“OCR 12345”小图片，不发送你的游戏截图。');ttk.Label(body,textvariable=status,wraplength=715).pack(fill='x',pady=10)
 tasks=queue.Queue();busy=False
 def values():return {p:{k:v.get().strip() for k,v in fields.items()} for p,fields in variables.items()}
 def save():
  try:save_profiles(path,values());win.destroy()
  except (ValueError,OSError) as e:messagebox.showerror('未保存',str(e),parent=win)
 def test():
  nonlocal busy
  if busy:return
  provider=next(p for p,tab in tabs.items() if str(tab)==notebook.select())
  try:client=Client(provider,validate_config(provider,values()[provider]))
  except ValueError as e:status.set(str(e));return
  busy=True;status.set('正在测试；本次会调用所选OCR接口，可能计费…')
  def work():
   try:
    image=Image.new('RGB',(400,140),'white');draw=ImageDraw.Draw(image)
    try:font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',36)
    except OSError:font=ImageFont.load_default()
    draw.text((25,45),'OCR 12345',fill='black',font=font);buffer=io.BytesIO();image.save(buffer,format='PNG');result=client.recognize(buffer.getvalue());tasks.put('接口成功返回：'+(result.get('text') or '未识别到测试文字')[:160])
   except Exception as e:
    message=str(e)
    for key in ('access_key','secret_key','session_token'):
     if client.config.get(key):message=message.replace(client.config[key],'[密钥]')
    tasks.put(message[:250])
  threading.Thread(target=work,daemon=True).start()
 def poll():
  nonlocal busy
  if not win.winfo_exists():return
  try:status.set(tasks.get_nowait());busy=False
  except queue.Empty:pass
  parent.after(250,poll)
 row=ttk.Frame(body);row.pack(fill='x');Button(row,text='测试连接（可能计费）',command=test,width=210).pack(side='left');Button(row,text='保存配置',command=save,primary=True).pack(side='right');parent.after(250,poll)
 return win
