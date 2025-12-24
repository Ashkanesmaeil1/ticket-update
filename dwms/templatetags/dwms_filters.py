from django import template

register = template.Library()

@register.filter
def movement_type_persian(value):
    """Convert movement type to Persian"""
    mapping = {
        'IN': 'ورودی',
        'OUT': 'خروجی',
        'ADJUSTMENT': 'اصلاح',
    }
    return mapping.get(value, value)

@register.filter
def persian_digits(value):
    """Convert English digits to Persian digits"""
    if value is None:
        return ""
    
    # Persian digit mapping
    persian_map = {
        '0': '۰',
        '1': '۱',
        '2': '۲',
        '3': '۳',
        '4': '۴',
        '5': '۵',
        '6': '۶',
        '7': '۷',
        '8': '۸',
        '9': '۹',
    }
    
    # Convert to string and replace each digit
    value_str = str(value)
    result = ''.join(persian_map.get(char, char) for char in value_str)
    return result

@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key"""
    if dictionary is None:
        return None
    return dictionary.get(key)

