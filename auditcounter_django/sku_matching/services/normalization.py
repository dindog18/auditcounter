"""Identity-preserving formatting and conservative explicit specification checks."""
import re
import unicodedata
from decimal import Decimal


def normalize_sku(value):
    return ' '.join(unicodedata.normalize('NFC',value or '').split()).casefold()


def normalize_description(value):
    return normalize_sku(value)


def normalize_unit(value):
    value=normalize_sku(value)
    return {**dict.fromkeys(('pc','pcs','pc.','pcs.','piece','pieces'),'pc'),
            **dict.fromkeys(('ea','ea.','each'),'ea'),
            **dict.fromkeys(('kg','kgs','kilogram','kilograms'),'kg'),
            **dict.fromkeys(('box','boxes'),'box')}.get(value,value)


def specifications(code,description):
    text=normalize_description(f'{code} {description}')
    values={}
    for match in re.finditer(r'(?<![\d.])(\d+(?:\.\d+)?)(?:\s*[-–]\s*(\d+(?:\.\d+)?))?\s*(kg|ml|mm|cm|btu|kw|hz|volts?|v|l|w)\b',text):
        first,second,unit=match.groups()
        unit='v' if unit.startswith('volt') else unit
        numeric=lambda value: format(Decimal(value).normalize(),'f')
        value=numeric(first)+(('-'+numeric(second)) if second else '')
        values.setdefault(unit,set()).add(value)
    manufacturers={word for word in re.findall(r'\b[\w]+\b',text) if word in {'samsung','lg','whirlpool','panasonic','electrolux','bosch','sharp','haier','toshiba','sony','daikin','midea'}}
    models=set(re.findall(r'\bmodel\s*[:#]?\s*([a-z0-9][a-z0-9/-]*)',normalize_description(description)))
    if not models:
        models={word for word in re.findall(r'\b[a-z0-9]+\b',normalize_description(description))
                if len(word)>=4 and re.search(r'[a-z]',word) and re.search(r'\d',word)
                and not re.fullmatch(r'\d+(?:kg|ml|mm|cm|btu|kw|hz|v|l|w)',word)}
    return dict(measures={key:sorted(value) for key,value in values.items()},manufacturer=sorted(manufacturers),model=sorted(models))


def incompatible_specs(left,right):
    a,b=specifications(left['code'],left.get('description','')),specifications(right['code'],right.get('description',''))
    reasons=[]
    for unit in a['measures'].keys() & b['measures'].keys():
        if a['measures'][unit]!=b['measures'][unit]:
            reasons.append(f'Explicit {unit} specifications differ.')
    for field in ('manufacturer','model'):
        if a[field] and b[field] and not set(a[field]) & set(b[field]):
            reasons.append(f'Explicit {field} identifiers differ.')
    return reasons
