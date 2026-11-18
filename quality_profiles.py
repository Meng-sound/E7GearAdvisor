"""Display rarity color plus level; roll-source exceptions are separate."""
from official_rolls import PROFILES
COLORS={'史诗':'红','英雄':'紫','稀有':'蓝'}
QUALITY_NAMES=[color+str(level) for level in (85,88,90,78,75,71,70,55) for color in ('红','紫','蓝')]
QUALITY_PROFILES={name:{'grade':grade,'level':level,'reforged':level==90,'roll_profile':PROFILES[-1] if level==90 else PROFILES[0],'note':'品质按颜色与等级显示；88级的跳值来源独立设置。'} for grade,color in COLORS.items() for level in range(1,100) for name in [color+str(level)]}
def infer_quality(level,grade,known_88=None):
    if level is None:return COLORS.get(grade,'')+'等级未知' if grade else '未识别'
    return COLORS[grade]+str(level) if grade in COLORS else str(level)+'级（颜色未知）'
