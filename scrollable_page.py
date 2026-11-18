"""Native long-form settings, with wheel handling scoped to this page."""
import tkinter as tk
from tkinter import ttk
from ui_theme import BG
class ScrollablePage(ttk.Frame):
 def __init__(self,parent,padding=12):
  super().__init__(parent);bar=ttk.Scrollbar(self);self.scrollbar=bar;bar.pack(side='right',fill='y');self.canvas=tk.Canvas(self,bg=BG,highlightthickness=0,yscrollcommand=self._scroll_changed);self.canvas.pack(fill='both',expand=True);bar.configure(command=self.canvas.yview)
  self.body=ttk.Frame(self.canvas,padding=padding);item=self.canvas.create_window(0,0,window=self.body,anchor='nw')
  self.body.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')));self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(item,width=e.width))
  self._binding=self.bind_all('<MouseWheel>',self._wheel,add='+');self.bind('<Destroy>',self._cleanup,add='+')
 def _scroll_changed(self,first,last):
  self.scrollbar.set(first,last)
  if float(first)<=0 and float(last)>=1:self.scrollbar.pack_forget()
  elif not self.scrollbar.winfo_manager():self.scrollbar.pack(side='right',fill='y',before=self.canvas)
 def _cleanup(self,event):
  if event.widget is self and self._binding:
   try:self._root()._unbind(('bind','all','<MouseWheel>'),self._binding)
   except tk.TclError:pass
   self._binding=None
 def _wheel(self,event):
  if not self.winfo_exists():return
  widget=event.widget
  while widget is not None:
   if widget is self:self.canvas.yview_scroll(-int(event.delta/120),'units');return 'break'
   widget=getattr(widget,'master',None)
