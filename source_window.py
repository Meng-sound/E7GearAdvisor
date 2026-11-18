"""Visible attribution for data, algorithms and bundled dependencies."""
import tkinter as tk,webbrowser
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from app_version import VERSION
from ui_theme import BG,CARD,TEXT,MUTED,FONT

SOURCES=[
 ('E7Pilot / E7Auto · E7Auto contributors','刷商店、红装购买、自动推图和月光剧场的源码、规则与模板。整合提交 da68ea89859501471cb3410d0a1b82dd7392b4e6。采用 PolyForm Noncommercial 1.0.0，保留作者声明及 vendor/e7pilot/LICENSE；该部分有非商业限制。','https://atomgit.com/gcw_dWaVd6eU/e7auto'),
 ('Neoinvoker / epic7-item-estimator','早期历史参考，提交52238a18b990bb3cd2eacddf48bfcccd5aac2e03。所核对版本未见顶层许可证，公开发布包排除相关历史算法对照源码及测试，仅保留来源说明。','https://github.com/Neoinvoker/epic7-item-estimator'),
 ('e7-e7-sidekick-resources · tsukiyakii4uu','社区英雄资料快照、部分刻印与基础资料参考。','https://github.com/tsukiyakii4uu/e7-e7-sidekick-resources'),
 ('EpicSevenDB 历史资料 · kmalone86/gamedatabase','开放型刻印资料，提交ad988d01b2c9892f01537f848dcff52ecf69ee66。按随附来源说明保留CC BY-NC-SA 4.0归属、非商业与相同方式共享要求；详见data/HERO-IMPRINT-SOURCES.md。','https://github.com/kmalone86/gamedatabase'),
 ('E7GW 公开战报','读取公开统计战报；校验页面结构，快照日期不是最近战斗时间；社区配装入口已移除。','https://e7gw.xyz/counters'),
 ('E7·WIKI · 康德、无敌兔酱及作业投稿作者','在线读取公开接口 https://admin.e7.wiki/api/open/epicseven/hero/card-list 和 https://admin.e7.wiki/api/open/epicseven/gvg_homework/page。按头像编号对应网站英雄代号，精确查询三人防守；保留投稿作者、装备、神器、打法和更新时间。胜负字段为用户反馈，不作为采样场次或实测胜率；仅查询，不提交投票。','https://e7.wiki/gvg-homework'),
 ('EP7 Guild War 公开战报','读取其公开 matchup 查询接口 https://ep7guildwar.duckdns.org/api/v1/matchups，严格匹配三名防守英雄；进攻胜负、平局直接来自其聚合统计。固定保存匿名查询身份并遵守网站额度，额度用完停止。更新时间是统计更新日期，不是对战日期。仅接入查询，未复制其网站源码。','https://ep7guild-war.vercel.app/en/meta'),
 ('百里 E7BOT 网页查询','团战窗口更多菜单提供网页入口；该页面要求登录，由用户在其网站查询。未接入其登录接口，未导入其战报，不代表与本工具或截图中的其他机器人有关联。','https://www.e7bot.top/#/e7/gvg'),
 ('百里 E7BOT 官方 Discord GVG 指南','官方作者说明 /gvg 三英雄查询、前十进攻队及胜负统计；/gvg-common-defense 和 /gvg-common-heros 为近30天统计。仅提供指南入口，未通过 Discord 自动发送命令或抓取聊天替代在线战报接口。','https://discord.com/channels/1133903405262327859/1396418865197744190/threads/1396430604836536433'),
 ('Fribbels 皮肤头像目录','社区项目提供的游戏头像缓存。检查文件校验值，仅下载缺失/变化的模板；游戏图像版权仍归原权利人。','https://github.com/fribbels/Fribbels-Epic-7-Optimizer/tree/main/data/cachedimages'),
 ('Fribbels Hero Library BS','角色面板扣除基础、套装、神器及已确认额外加成后的配装分；和装备副属性GS不同。','https://github.com/fribbels/fribbels.github.io/blob/master/e7/heroBuilds.js'),
 ('Fribbels GS / ItemDb / StatCalculator','GS 按副属性固定系数计算，每件依 Java Math.round 取整，六件分数相加；参考面板显示同套装组样本 GS 的中位数。','https://github.com/fribbels/Fribbels-Epic-7-Optimizer/blob/main/backend/src/main/java/com/fribbels/db/ItemDb.java'),
 ('Ark Guild War Tracker','公开匿名团战记录；按敌方三人精确匹配。胜败按进攻方视角汇总，展示来源提供的战报时间范围。','https://ark-gw-tracker-web.vercel.app/'),
 ('Fribbels GW Meta Tracker','历史团战数据源，官网已声明不再更新；作为可选历史来源，数据不可视为当前版本胜率。','https://fribbels.github.io/e7/gw-meta.html'),
 ('火山引擎图像技术 OCR','OCRNormal 接口；使用用户填写的AK/SK签名，按服务商规则计费。','https://www.volcengine.com/docs/6790'),
 ('百度智能云文字识别','通用文字识别高精度版 accurate / accurate_basic；默认使用含位置版本。','https://cloud.baidu.com/doc/OCR/index.html'),
 ('阿里云文字识别','RecognizeAdvanced 接口；ACS3签名，使用用户开通的服务及权限。','https://help.aliyun.com/zh/ocr/'),
 ('Fribbels Epic 7 Optimizer','角色资料与装备数据格式的参考来源。当前版本暂不包含配装器组件。','https://github.com/fribbels/Fribbels-Epic-7-Optimizer'),
 ('Fribbels Hero Library','社区配装样本、套装使用率及统计面板。中位数参考不代表唯一最佳配装。','https://fribbels.github.io/e7/hero-library.html'),
 ('用户提供的强化流程图','左右三件门槛、速度路线、右三件固定主属性限制；可在设置中修改。',''),
 ('Epic Seven／Smilegate','英雄、装备及游戏内图标的原始来源。非官方工具，与游戏运营方无隶属关系。','https://epic7.onstove.com/'),
 ('RapidOCR／PP-OCRv4／ONNX Runtime','本地文字检测与识别；相关许可证随识别组件保留。','https://github.com/RapidAI/RapidOCR'),
 ('CPython、Tcl/Tk、Pillow','桌面程序运行时、界面与图像处理；许可证随包保留。','https://www.python.org/'),
 ('Windows OCR','系统自带文字识别与本机截图。','https://learn.microsoft.com/uwp/api/windows.media.ocr'),
 ('用户配置的视觉模型','按用户选择发送截图并提取字段；模型结果经本地校验，分数由本地计算。',''),
 ('Fribbels StatCalculator','六件装备分数与角色属性计算的实现参考。','https://github.com/fribbels/Fribbels-Epic-7-Optimizer/blob/main/backend/src/main/java/com/fribbels/core/StatCalculator.java'),
 ('Fribbels 游戏基础资料接口','英雄属性同步使用的公开数据地址；配装统计来自Hero Library。','https://e7-optimizer-game-data.s3-accelerate.amazonaws.com/herodata.json'),
 ('E7GW 公开资源目录','神器与部分图像资源的下载来源；资源权利归原作者及游戏权利人，不因本工具提供下载而转移。','https://e7gw.xyz/'),
 ('游戏装备机制公告','强化、重铸规则的官方公告参考；适用版本以游戏当前说明为准。','https://sdk-page.onstove.com/epicseven/tw/view/7872400'),
 ('装备机制社区说明','真假88等社区术语说明参考。','https://www.taptap.cn/moment/436809716014777258'),
 ('角色官方社区公告','黎洁特角色资料与头像背景说明参考。','https://www.taptap.cn/moment/848954491758707729'),
 ('windows-capture · NiiightmareXD','Windows Graphics Capture窗口捕获库；保留随包许可证和分发元数据。','https://github.com/NiiightmareXD/windows-capture'),
 ('PaddleOCR / PP-OCR','本地文字检测和识别模型来源。','https://github.com/PaddlePaddle/PaddleOCR'),
 ('ONNX Runtime · Microsoft','本地神经网络推理运行时。','https://github.com/microsoft/onnxruntime'),
 ('OpenCV','图标、模板和图像处理。','https://github.com/opencv/opencv'),
 ('NumPy','图像数组与数值运算。','https://numpy.org/'),
 ('Pillow','图像读取、缩放和界面图像处理。','https://python-pillow.org/'),
 ('Tcl/Tk','桌面界面工具包。','https://www.tcl.tk/'),
 ('pywin32 · mhammond','Windows窗口消息及系统接口。','https://github.com/mhammond/pywin32'),
 ('python-mss','随自动任务依赖提供的截图库；当前遮挡取图优先使用Windows图形捕获。','https://github.com/BoboTiG/python-mss'),
 ('PyYAML','任务规则和设置文件解析。','https://github.com/yaml/pyyaml'),
 ('E7GW 完整进攻战报','公开战报页面与数据字段参考。','https://e7gw.xyz/full-attack'),
 ('Fribbels 配装统计接口','社区配装样本同步实际使用的接口地址。','https://krivpfvxi0.execute-api.us-west-2.amazonaws.com/dev/getBuilds'),
 ('Fribbels 历史团战接口','历史防守阵容战报查询接口；不是当前实时战报。','https://z4tfy2r5kc.execute-api.us-west-2.amazonaws.com/dev/getDef'),
 ('Fribbels 本地化资料','中文名称、繁体名称及本地化文本参考。','https://github.com/fribbels/Fribbels-Epic-7-Optimizer/tree/main/data/locales'),
 ('英雄外号社区说明','角色外号及别名映射参考；有歧义时不代表唯一对应。','https://www.taptap.cn/moment/694233215501598946'),
 ('哔哩哔哩游戏Wiki · 幻影的泰妮布里雅','角色名称与社区称呼参考。','https://wiki.biligame.com/epic7/幻影的泰妮布里雅'),
 ('哔哩哔哩游戏Wiki · 海边的维尔萝娜','角色名称与社区称呼参考。','https://wiki.biligame.com/epic7/海边的维尔萝娜'),
]

PROJECT_INFO='''装备强化计算器

本项目以源代码公开的方式提供，供第七史诗玩家学习、研究与交流。功能包括装备识别与评分、角色面板参考、角色总分计算以及后台自动任务。

本工具为社区开发的非官方软件，与Epic Seven、Smilegate、STOVE及其运营方无隶属、合作或授权关系。

开源与许可说明

本项目整合了第三方代码、数据、算法和图像。项目自有代码与各第三方内容的权利分别归相应权利人所有，不能将整包内容一概视为本项目原创或统一许可。

源代码公开不等于可任意商用或移除署名。E7Pilot相关部分适用PolyForm Noncommercial 1.0.0；部分刻印数据按CC BY-NC-SA 4.0来源说明保留。使用、修改或分发时，请保留适用的许可证、版权、作者及来源声明，并遵守相应限制。

未明确授权的历史参考代码，不能仅凭公开仓库或本页面取得新的再分发权利。第三方游戏图像、名称和商标仍归原权利人所有。

详细来源见“参考与致谢”，适用条款见随包的vendor/e7pilot/LICENSE、各组件许可证、UPSTREAM-NOTICE.md及data/HERO-IMPRINT-SOURCES.md。本说明和免责声明不替代或修改这些许可证。
'''

DISCLAIMER='''免责声明

1. 非官方性质
本软件是独立的社区辅助工具，不代表游戏开发商、发行商、运营方或所引用项目的立场，亦不意味着获得其认可。

2. 识别与数据准确性
截图识别、装备评分、角色计算、社区配装和战报统计可能存在遗漏、误差、样本偏差、资料过期或区服差异，不保证完整、准确、实时或适合特定用途。操作与资源投入前，请以游戏内当前信息为准并核对。

3. 自动操作与账号
自动任务会模拟窗口操作，可能消耗金币、天空石、体力或观览券，也可能因网络、加载、游戏更新或识别错误而中断或误操作。请在理解功能后自行配置和监督。使用前应了解并遵守游戏当前用户协议、运营规则及适用法律；本软件不承诺账号不会受到限制或处罚。

4. 网络服务与隐私
启用在线资料同步会连接相应数据站点。选择云OCR或视觉模型服务时，待识别截图区域会发送给所选服务商，可能产生费用，并受其服务条款与隐私政策约束。请自行管理密钥、个人信息和相关权限。

5. 使用与分发
请勿将本软件用于侵权、违法或违反适用许可的用途。公开源代码不免除第三方许可证义务，不授权移除作者声明、盗用游戏素材，或对受非商业限制的组件进行未经许可的商业分发。

6. 保证与责任
软件按现状提供。在适用法律允许的范围内，不对其准确性、持续可用性、兼容性或特定用途适用性作出保证。使用者应自行评估使用、修改和分发的风险。本声明不排除或限制依法不得排除、限制的责任，也不影响适用许可证和强制性法律规定。

7. 反馈与更正
如发现来源署名、许可说明、资料或功能存在问题，请通过项目正式发布仓库的Issue联系维护者。项目仓库地址尚未配置时，以实际发布渠道提供的信息为准。
'''

def attribution_text():
 return '\n\n'.join(name+'\n'+description+'\n'+(url or '来源：用户提供的本地材料或用户自行配置，暂无统一公开地址。') for name,description,url in SOURCES)

def about_document():
 return '# 关于装备强化计算器\n\n'+PROJECT_INFO+'\n## 参考与致谢\n\n'+attribution_text()+'\n\n## 免责声明\n\n'+DISCLAIMER

def show_sources(parent):
 existing=getattr(parent,'about_window',None)
 if existing is not None and existing.winfo_exists():existing.deiconify();existing.lift();return existing
 win=tk.Toplevel(parent);parent.about_window=win;win.title('关于 · 装备强化计算器');win.geometry('860x720');win.minsize(650,480);win.configure(bg=BG)
 header=ttk.Frame(win,padding=18);header.pack(fill='x')
 ttk.Label(header,text='关于装备强化计算器',font=(FONT,18,'bold')).pack(anchor='w')
 ttk.Label(header,text='版本 '+VERSION+' · 源码公开 · 社区非官方工具',foreground=MUTED).pack(anchor='w',pady=(6,0))
 book=ttk.Notebook(win);book.pack(fill='both',expand=True,padx=16,pady=(0,16));win.about_tabs=book
 for title,content in [('项目与许可',PROJECT_INFO),('参考与致谢',attribution_text()),('免责声明',DISCLAIMER)]:
  if title=='项目与许可':
   from software_update_ui import load_config
   repo=load_config(parent).get('repository','')
   content+='\n项目发布仓库：'+('https://github.com/'+repo if repo else '尚未配置，以维护者后续正式发布地址为准。')
  page=ttk.Frame(book);book.add(page,text=title)
  text=ScrolledText(page,wrap='word',bg=CARD,fg=TEXT,insertbackground=TEXT,relief='flat',font=(FONT,10),padx=18,pady=16,spacing3=7)
  text.pack(fill='both',expand=True);text.insert('1.0',content)
  import re
  for index,match in enumerate(re.finditer(r'https?://[^\s]+',content)):
   tag='url'+str(index);text.tag_add(tag,f'1.0+{match.start()}c',f'1.0+{match.end()}c');text.tag_configure(tag,foreground='#84b5ff',underline=True)
   text.tag_bind(tag,'<Button-1>',lambda event,url=match.group():webbrowser.open(url))
   text.tag_bind(tag,'<Enter>',lambda event,w=text:w.configure(cursor='hand2'));text.tag_bind(tag,'<Leave>',lambda event,w=text:w.configure(cursor='xterm'))
  text.configure(state='disabled')
 return win
