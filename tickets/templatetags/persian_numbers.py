from django import template

register = template.Library()

def _persian_to_latin(text):
    """
    Convert Persian digits to Latin digits.
    Used for search normalization.
    """
    persian_to_latin_map = {
        '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
        '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
    }
    result = ''
    for char in str(text):
        result += persian_to_latin_map.get(char, char)
    return result

def _latin_to_persian_digits(value_str):
    """
    Convert Latin digits to Persian digits in a string.
    Preserves non-digit characters.
    """
    persian_map = {
        '0': '۰', '1': '۱', '2': '۲', '3': '۳', '4': '۴',
        '5': '۵', '6': '۶', '7': '۷', '8': '۸', '9': '۹',
    }
    return ''.join(persian_map.get(char, char) for char in value_str)

@register.filter
def persian_id(value):
    """
    Convert ID to Persian format with hash prefix preservation.
    
    This filter is specifically designed for ticket/task IDs that use
    the format #123 or #005. It preserves the hash prefix (#) and
    converts only the numerical digits to Persian.
    
    Examples:
        - #101 → #۱۰۱
        - #005 → #۰۰۵ (zero-padding maintained)
        - 123 → ۱۲۳ (no prefix)
        - #12345 → #۱۲۳۴۵
    
    Zero-padding is maintained exactly as provided.
    """
    if value is None:
        return ""
    
    # Convert to string
    value_str = str(value)
    
    # Check if it starts with # (hash prefix)
    has_hash = value_str.startswith('#')
    if has_hash:
        prefix = '#'
        number_part = value_str[1:]
    else:
        prefix = ''
        number_part = value_str
    
    # Convert digits to Persian (preserves zero-padding)
    persian_number = _latin_to_persian_digits(number_part)
    
    return f"{prefix}{persian_number}"

@register.filter
def persian_digits(value):
    """
    Convert English digits to Persian digits with thousands separator support.
    
    This filter transforms numerical values (integers, floats, or strings) into
    Persian digit format while preserving thousands separators using Persian comma (،).
    
    Examples:
        - 125 → ۱۲۵
        - 1500 → ۱٬۵۰۰
        - 0 → ۰
        - None → "" (empty string)
    
    The transformation occurs ONLY at the presentation layer. Backend data integrity
    is maintained as integers/floats are converted to strings for display only.
    """
    if value is None:
        return ""
    
    # Handle zero values explicitly
    if value == 0 or value == "0":
        return "۰"
    
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
    
    # Convert to string
    value_str = str(value)
    
    # Handle negative numbers
    is_negative = value_str.startswith('-')
    if is_negative:
        value_str = value_str[1:]
    
    # Handle decimal numbers (if any)
    if '.' in value_str:
        parts = value_str.split('.')
        integer_part = parts[0]
        decimal_part = parts[1]
    else:
        integer_part = value_str
        decimal_part = None
    
    # Convert digits to Persian first
    persian_integer_str = ''.join(persian_map.get(char, char) for char in integer_part)
    
    # Add thousands separators (Persian comma) for integer part
    # Format: 1500 → 1٬500 (using Persian comma)
    if len(persian_integer_str) > 3:
        persian_integer_str = persian_integer_str[::-1]  # Reverse for grouping
        persian_integer_str = '٬'.join(persian_integer_str[i:i+3] for i in range(0, len(persian_integer_str), 3))
        persian_integer_str = persian_integer_str[::-1]  # Reverse back
    
    persian_integer = persian_integer_str
    
    # Add decimal part if exists
    if decimal_part:
        persian_decimal = ''.join(persian_map.get(char, char) for char in decimal_part)
        result = f"{persian_integer}.{persian_decimal}"
    else:
        result = persian_integer
    
    # Add negative sign if needed
    if is_negative:
        result = f"-{result}"
    
    return result

