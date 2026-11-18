"""Filters operate on canonical hero IDs, including skins mapped to a hero."""
def attack_rows(record,minimum=1,sort='样本数',include=(),exclude=(),partner=()):
 required=set(include);blocked=set(exclude)|set(partner)
 rows=[row for row in record.get('offenses',[]) if row['samples']>=minimum and required.issubset(row['heroes']) and not blocked.intersection(row['heroes'])]
 rows.sort(key=(lambda r:(-r['wins']/max(1,r['samples']),-r['samples'])) if sort=='胜率' else (lambda r:(-r['samples'],-r['wins'])))
 return rows

def guide_rows(record,include=(),exclude=(),partner=()):
 required=set(include);blocked=set(exclude)|set(partner)
 return [row for row in record.get('guides',[]) if required.issubset(row['heroes']) and not blocked.intersection(row['heroes'])]
