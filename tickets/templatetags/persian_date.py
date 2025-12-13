from django import template
from django.utils import timezone
import jdatetime
import zoneinfo

register = template.Library()

@register.filter
def persian_date(value):
    """Convert datetime to Persian date format"""
    if value is None:
        return ""
    
    # Convert to Tehran timezone if it's timezone-aware
    if timezone.is_aware(value):
        tehran_tz = zoneinfo.ZoneInfo('Asia/Tehran')
        value = value.astimezone(tehran_tz)
    
    # Convert to Persian calendar
    persian_date = jdatetime.datetime.fromgregorian(datetime=value)
    
    # Format: 1402/12/25 14:30
    return persian_date.strftime('%Y/%m/%d %H:%M')

@register.filter
def persian_date_only(value):
    """Convert datetime to Persian date only (without time)"""
    if value is None:
        return ""
    
    # Convert to Tehran timezone if it's timezone-aware
    if timezone.is_aware(value):
        tehran_tz = zoneinfo.ZoneInfo('Asia/Tehran')
        value = value.astimezone(tehran_tz)
    
    # Convert to Persian calendar
    persian_date = jdatetime.datetime.fromgregorian(datetime=value)
    
    # Format: 1402/12/25
    return persian_date.strftime('%Y/%m/%d')

@register.filter
def persian_time_only(value):
    """Convert datetime to Persian time only"""
    if value is None:
        return ""
    
    # Convert to Tehran timezone if it's timezone-aware
    if timezone.is_aware(value):
        tehran_tz = zoneinfo.ZoneInfo('Asia/Tehran')
        value = value.astimezone(tehran_tz)
    
    # Format: 14:30
    return value.strftime('%H:%M')

@register.filter
def persian_month_name(value):
    """Get Persian month name"""
    if value is None:
        return ""
    
    # Convert to Tehran timezone if it's timezone-aware
    if timezone.is_aware(value):
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
    
    # Convert to Tehran timezone if it's timezone-aware
    if timezone.is_aware(value):
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