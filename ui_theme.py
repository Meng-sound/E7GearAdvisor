"""Calculator palette and rounded controls, independent from the Fribbels UI."""
import os,tkinter as tk
BG='#171b23';CARD='#202630';FIELD='#272e3b';EDGE='#394355';TEXT='#edf2fa';MUTED='#929db0';ACCENT='#4b73ff';SUCCESS='#55d7a0';GOLD='#bdcbff';FONT='Microsoft YaHei UI'

class Card(tk.Canvas):
 def __init__(self,parent,height=240,padding=18,color=CARD):
  super().__init__(parent,height=height,bg=BG,highlightthickness=0,bd=0);self.padding=padding
  self.shape=self.create_polygon(0,0,1,0,1,1,fill=color,outline=EDGE,smooth=True,splinesteps=24)
  self.body=tk.Frame(self,bg=color);self.window=self.create_window(padding,padding,window=self.body,anchor='nw');self.bind('<Configure>',self.resize)
 def resize(self,e):
  w,h=e.width,e.height;r=15;self.coords(self.shape,r,0,w-r,0,w,0,w,r,w,h-r,w,h,w-r,h,r,h,0,h,0,h-r,0,r,0,0);self.itemconfigure(self.window,width=max(1,w-2*self.padding),height=max(1,h-2*self.padding))

class Button(tk.Canvas):
 def __init__(self,parent,text,command,width=145,height=38,primary=False):
  super().__init__(parent,width=width,height=height,bg=BG,bd=0,highlightthickness=0,cursor='hand2');self.command=command;self.primary=primary;self.color=ACCENT if primary else FIELD
  self.shape=self.create_polygon(0,0,1,0,1,1,fill=self.color,outline=ACCENT if primary else EDGE,smooth=True,splinesteps=20)
  self.label=self.create_text(width/2,height/2,text=text,fill=TEXT,font=(FONT,9,'bold' if primary else 'normal'));self.bind('<Configure>',self.resize);self.bind('<Button-1>',lambda e:self.command());self.bind('<Enter>',lambda e:self.itemconfigure(self.shape,fill='#5d82ff' if self.primary else '#323b4b'));self.bind('<Leave>',lambda e:self.itemconfigure(self.shape,fill=self.color))
 def resize(self,e):
  w,h=e.width,e.height;r=10;self.coords(self.shape,r,1,w-r,1,w-1,1,w-1,r,w-1,h-r,w-1,h-1,w-r,h-1,r,h-1,1,h-1,1,h-r,1,r,1,1);self.coords(self.label,w/2,h/2)

def dark_title(window):
 if os.name!='nt':return
 try:
  import ctypes
  from ctypes import wintypes
  user32=ctypes.windll.user32;user32.GetParent.restype=wintypes.HWND;hwnd=user32.GetParent(window.winfo_id());value=ctypes.c_int(1)
  ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd,20,ctypes.byref(value),ctypes.sizeof(value))
 except (OSError,AttributeError,tk.TclError):pass
