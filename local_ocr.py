"""Offline PP-OCR detector/recognizer, with Windows capture and secondary OCR."""
import sys,threading,hashlib,copy,os
from collections import OrderedDict
from pathlib import Path
from PIL import Image,ImageOps
from ocr import WindowsOCR,reconstruct_lines

def ocr_threads():
    default=2  # Conservative default measured on the desktop screenshot fixtures.
    try:value=int(os.environ.get('E7_OCR_THREADS',default))
    except (TypeError,ValueError):value=default
    return max(1,min(6,value))

class LocalOCR:
    engine_name='PP-OCRv4 / ONNX Runtime'
    def __init__(self):
        neural=Path(__file__).parent/'neural'
        if str(neural) not in sys.path:sys.path.insert(0,str(neural))
        import onnxruntime as ort
        ort.disable_telemetry_events()
        from rapidocr_onnxruntime import RapidOCR
        self.threads=ocr_threads()
        self.engine=RapidOCR(intra_op_num_threads=self.threads,inter_op_num_threads=1,print_verbose=False,text_score=.5,det_box_thresh=.4)
        self.windows=None;self.lock=threading.Lock();self.calls=0;self.fallbacks=0;self.cache_hits=0;self._cache=OrderedDict()
    def secondary(self):
        if self.windows is None:self.windows=WindowsOCR()
        return self.windows
    def request(self,**request):
        if request.get('action')=='languages':return {'ok':True,'languages':['zh-Hans-CN','en-US'],'engine':self.engine_name}
        if request.get('capture_only') or request.get('rect'):return self.secondary().request(**request)
        path=request.get('path')
        if not path:raise ValueError('缺少待识别图像')
        with self.lock:
            with Image.open(path) as source:
                picture=source.convert('RGB')
                single_line=request.get('single_line',False) or (request.get('language')=='en-US' and picture.height<500 and picture.width<1200)
                key=(picture.size,hashlib.blake2b(picture.tobytes(),digest_size=16).digest(),single_line,request.get('crop_text',False),request.get('yellow_only',False))
                if key in self._cache:
                    self.cache_hits+=1;self._cache.move_to_end(key);return copy.deepcopy(self._cache[key])
                self.calls+=1
                if request.get('crop_text'):
                    import numpy as np
                    pixels=np.asarray(picture);mask=((pixels.min(axis=2)>185)&((pixels.max(axis=2).astype(int)-pixels.min(axis=2))<55))
                    rows=np.where(mask.sum(axis=1)>=12)[0]
                    if len(rows)>10:
                        top,bottom=int(rows[0]),int(rows[-1])+1;cols=np.where(mask[top:bottom].sum(axis=0)>0)[0]
                        if len(cols)>10:picture=ImageOps.expand(picture.crop((int(cols[0]),top,int(cols[-1])+1,bottom)),6,fill='#07111c')
                if request.get('yellow_only'):
                    import numpy as np
                    raw=self.engine.load_img(picture);boxes,det_time=self.engine.text_det(raw);selected=[]
                    for box in boxes if boxes is not None else []:
                        x0,y0=np.maximum(np.floor(box.min(axis=0)).astype(int),0);x1,y1=np.minimum(np.ceil(box.max(axis=0)).astype(int),[picture.width,picture.height])
                        patch=np.asarray(picture)[y0:y1,x0:x1].astype(int)
                        if patch.size==0:continue
                        r,g,b=patch[:,:,0],patch[:,:,1],patch[:,:,2]
                        if ((r>155)&(g>120)&(b<np.minimum(r,g)*.78)&(r>g*.85)).mean()>=.04:selected.append(box)
                    if selected:
                        crops=self.engine.get_crop_img_list(raw,np.asarray(selected));values,rec_time=self.engine.text_rec(crops)
                        result=[(box,text,score) for box,(text,score) in zip(selected,values)];elapsed=[det_time,rec_time]
                    else:result,elapsed=self.engine(picture,use_cls=False)
                elif single_line:
                    single,elapsed=self.engine(picture,use_det=False,use_cls=False)
                    result=[([[0,0],[picture.width,0],[picture.width,picture.height],[0,picture.height]],text,score) for text,score in single or [] if score>=.8]
                    if not result:result,elapsed=self.engine(picture,use_cls=False)
                else:result,elapsed=self.engine(picture,use_cls=False)
                if not result and picture.height<400 and picture.width<1100:
                    single,elapsed=self.engine(picture,use_det=False,use_cls=False)
                    if single:
                        result=[([[0,0],[picture.width,0],[picture.width,picture.height],[0,picture.height]],text,score) for text,score in single if score>=.5]
            words=[]
            for box,text,confidence in result or []:
                if confidence<.5:continue
                xs=[p[0] for p in box];ys=[p[1] for p in box]
                words.append({'text':text,'x':min(xs),'y':min(ys),'w':max(xs)-min(xs),'h':max(ys)-min(ys),'confidence':float(confidence)})
            if not words:
                self.fallbacks+=1
                return self.secondary().request(**request)
            lines=[{'text':w['text'],'words':[w]} for w in words]
            value={'ok':True,'text':reconstruct_lines(lines),'lines':lines,'engine':self.engine_name,'elapsed':sum(elapsed or [])}
            self._cache[key]=copy.deepcopy(value)
            if len(self._cache)>64:self._cache.popitem(last=False)
            return value
    def recognize_tiles(self,tiles):
        with self.lock:
            self.calls+=1
            images=[self.engine.load_img(tile) for tile in tiles]
            original=self.engine.text_rec.rec_batch_num
            try:
                self.engine.text_rec.rec_batch_num=16
                values,_=self.engine.text_rec(images)
                return values
            finally:self.engine.text_rec.rec_batch_num=original
    def close(self):
        if self.windows:self.windows.close();self.windows=None
        self.engine=None
