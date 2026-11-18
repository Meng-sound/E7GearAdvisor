"""Black loading frames keep their capture session alive and never reach OCR."""
import time

def wait_for_picture(capture,guard,on_loading=lambda:None,on_ready=lambda:None,wait=time.sleep):
 loading=False
 while True:
  guard();picture=capture();guard()
  if not picture.info.get('loading',False):
   if loading:on_ready()
   return picture
  if not loading:on_loading();loading=True
  wait(.15)
