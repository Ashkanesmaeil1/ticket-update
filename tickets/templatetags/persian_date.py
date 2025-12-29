from django import template
from django.utils import timezone
import jdatetime
import zoneinfo
from datetime import date, datetime

register = template.Library()

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
def persian_date(value):
    """Convert datetime to Persian date format"""
    if value is None:
        return ""
    
    # Handle datetime.date objects (from DateField)
    if isinstance(value, date) and not isinstance(value, datetime):
        # Convert date to datetime at midnight for conversion
        value = datetime.combine(value, datetime.min.time())
    
    # Convert to Tehran timezone if it's timezone-aware datetime
    if isinstance(value, datetime) and timezone.is_aware(value):
        tehran_tz = zoneinfo.ZoneInfo('Asia/Tehran')
        value = value.astimezone(tehran_tz)
    
    # Convert to Persian calendar
    persian_date = jdatetime.datetime.fromgregorian(datetime=value)
    
    # Format: 1402/12/25 14:30 (or just date if original was date)
    if isinstance(value, datetime) and not isinstance(value, date):
        formatted = persian_date.strftime('%Y/%m/%d %H:%M')
    else:
        # For date-only fields, don't show time
        formatted = persian_date.strftime('%Y/%m/%d')
    
    # Convert digits to Persian
    return _latin_to_persian_digits(formatted)

@register.filter
def persian_date_only(value):
    """Convert datetime to Persian date only (without time)"""
    if value is None:
        return ""
    
    # Handle datetime.date objects (from DateField)
    if isinstance(value, date) and not isinstance(value, datetime):
        # Convert date to datetime at midnight for conversion
        value = datetime.combine(value, datetime.min.time())
    
    # Convert to Tehran timezone if it's timezone-aware datetime
    if isinstance(value, datetime) and timezone.is_aware(value):
        tehran_tz = zoneinfo.ZoneInfo('Asia/Tehran')
        value = value.astimezone(tehran_tz)
    
    # Convert to Persian calendar
    persian_date = jdatetime.datetime.fromgregorian(datetime=value)
    
    # Format: 1402/12/25
    formatted = persian_date.strftime('%Y/%m/%d')
    # Convert digits to Persian
    return _latin_to_persian_digits(formatted)

@register.filter
def persian_time_only(value):
    """Convert datetime to Persian time only"""
    if value is None:
        return ""
    
    # Handle datetime.date objects (from DateField) - no time component
    if isinstance(value, date) and not isinstance(value, datetime):
        return ""  # DateField has no time
    
    # Convert to Tehran timezone if it's timezone-aware datetime
    if isinstance(value, datetime) and timezone.is_aware(value):
        tehran_tz = zoneinfo.ZoneInfo('Asia/Tehran')
        value = value.astimezone(tehran_tz)
    
    # Format: 14:30
    formatted = value.strftime('%H:%M')
    # Convert digits to Persian
    return _latin_to_persian_digits(formatted)

@register.filter
def persian_month_name(value):
    """Get Persian month name"""
    if value is None:
        return ""
    
    # Handle datetime.date objects (from DateField)
    if isinstance(value, date) and not isinstance(value, datetime):
        # Convert date to datetime at midnight for conversion
        value = datetime.combine(value, datetime.min.time())
    
    # Convert to Tehran timezone if it's timezone-aware datetime
    if isinstance(value, datetime) and timezone.is_aware(value):
        tehran_tz = zoneinfo.ZoneInfo('Asia/Tehran')
        value = value.astimezone(tehran_tz)
    
    # Convert to Persian calendar
    persian_date = jdatetime.datetime.fromgregorian(datetime=value)
    
    # Persian month names
    month_names = {
        1: 'فروردین',
        2: 'اردیبهشت',
        3: 'خرداد',
        4: 'تیر',
        5: 'مرداد',
        6: 'شهریور',
        7: 'مهر',
        8: 'آبان',
        9: 'آذر',
        10: 'دی',
        11: 'بهمن',
        12: 'اسفند'
    }
    
    return month_names.get(persian_date.month, '')

@register.filter
def persian_weekday_name(value):
    """Get Persian weekday name"""
    if value is None:
        return ""
    
    # Handle datetime.date objects (from DateField)
    if isinstance(value, date) and not isinstance(value, datetime):
        # Convert date to datetime at midnight for conversion
        value = datetime.combine(value, datetime.min.time())
    
    # Convert to Tehran timezone if it's timezone-aware datetime
    if isinstance(value, datetime) and timezone.is_aware(value):
        tehran_tz = zoneinfo.ZoneInfo('Asia/Tehran')
        value = value.astimezone(tehran_tz)
    
    # Convert to Persian calendar
    persian_date = jdatetime.datetime.fromgregorian(datetime=value)
    
    # Persian weekday names
    weekday_names = {
        0: 'شنبه',
        1: 'یکشنبه',
        2: 'دوشنبه',
        3: 'سه‌شنبه',
        4: 'چهارشنبه',
        5: 'پنج‌شنبه',
        6: 'جمعه'
    }
    
    return weekday_names.get(persian_date.weekday(), '') 