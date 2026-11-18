"""Stable scoring IDs and migration of the legacy custom override."""
MODE_LABELS={'gs':'Fribbels 装备 GS','role':'Fribbels 角色换算','custom':'自定义算法'}
def migrate_mode(settings,legacy_custom_enabled=False):
 mode=settings.get('score_mode','gs')
 if settings.get('score_mode_schema')!=2 and mode=='role' and legacy_custom_enabled:return 'custom'
 return mode if mode in MODE_LABELS else 'gs'
