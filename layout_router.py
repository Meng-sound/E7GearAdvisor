"""Recognize only the page title before selecting the expensive OCR region."""
from pathlib import Path
from core import _clean
def page_hint(image,ocr,directory):
    if image.width/image.height<1.6:return None
    path=Path(directory)/'page-title.png';image.crop((75,38,320,121)).save(path)
    text=_clean(ocr.request(path=str(path),single_line=True,crop_text=True).get('text',''))
    if '背包' in text:return 'inventory'
    if '强化装备' in text or '強化裝備' in text:return 'enhance'
    if '钢铁工坊' in text or '鋼鐵工坊' in text:return 'forge'
    return None
