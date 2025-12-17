"""
Modular Jalali (Persian/Shamsi) Calendar Service

This module provides a basic, modular implementation for Jalali calendar functionality.
It is designed to be easily replaceable when a formal API is provided.

The service handles:
- Conversion between Jalali and Gregorian dates
- Date validation
- Date formatting
"""

import jdatetime
from django.utils import timezone
from datetime import datetime

# Handle zoneinfo import compatibility (Python 3.8 vs 3.9+)
# Use lazy import pattern - only fail when actually used
_zoneinfo = None
try:
    import zoneinfo
    _zoneinfo = zoneinfo
except ImportError:
    try:
        from backports import zoneinfo
        _zoneinfo = zoneinfo
    except ImportError:
        # zoneinfo not available - will fail when methods are called
        pass


class JalaliCalendarService:
    """
    Basic Jalali calendar service module.
    
    This is a placeholder implementation that can be replaced with a formal API later.
    """
    
    @staticmethod
    def jalali_to_gregorian(year, month, day, hour=0, minute=0):
        """
        Convert Jalali date to Gregorian datetime.
        
        Args:
            year (int): Jalali year (e.g., 1403)
            month (int): Jalali month (1-12)
            day (int): Jalali day (1-31)
            hour (int): Hour (0-23), default 0
            minute (int): Minute (0-59), default 0
        
        Returns:
            datetime: Gregorian datetime object in Tehran timezone
        
        Raises:
            ValueError: If the Jalali date is invalid
        """
        try:
            # Create Jalali datetime
            jalali_dt = jdatetime.datetime(year, month, day, hour, minute)
            # Convert to Gregorian
            gregorian_dt = jalali_dt.togregorian()
            # Make timezone-aware (Tehran timezone)
            if _zoneinfo is None:
                raise ImportError("zoneinfo module not available. Install backports.zoneinfo for Python 3.8")
            tehran_tz = _zoneinfo.ZoneInfo('Asia/Tehran')
            return timezone.make_aware(gregorian_dt, timezone=tehran_tz)
        except (ValueError, jdatetime.JalaliDateOutOfRange) as e:
            raise ValueError(f"Invalid Jalali date: {year}/{month}/{day}") from e
    
    @staticmethod
    def gregorian_to_jalali(dt):
        """
        Convert Gregorian datetime to Jalali date components.
        
        Args:
            dt (datetime): Gregorian datetime object
        
        Returns:
            dict: Dictionary with keys 'year', 'month', 'day', 'hour', 'minute'
        """
        if timezone.is_aware(dt):
            # Convert to Tehran timezone
            if _zoneinfo is None:
                raise ImportError("zoneinfo module not available. Install backports.zoneinfo for Python 3.8")
            tehran_tz = _zoneinfo.ZoneInfo('Asia/Tehran')
            dt = dt.astimezone(tehran_tz)
        
        # Convert to Jalali
        jalali_dt = jdatetime.datetime.fromgregorian(datetime=dt)
        
        return {
            'year': jalali_dt.year,
            'month': jalali_dt.month,
            'day': jalali_dt.day,
            'hour': jalali_dt.hour,
            'minute': jalali_dt.minute,
        }
    
    @staticmethod
    def validate_jalali_date(year, month, day):
        """
        Validate if a Jalali date is valid.
        
        Args:
            year (int): Jalali year
            month (int): Jalali month
            day (int): Jalali day
        
        Returns:
            bool: True if valid, False otherwise
        """
        try:
            jdatetime.date(year, month, day)
            return True
        except (ValueError, jdatetime.JalaliDateOutOfRange):
            return False
    
    @staticmethod
    def get_current_jalali_date():
        """
        Get current date in Jalali calendar.
        
        Returns:
            dict: Dictionary with keys 'year', 'month', 'day', 'hour', 'minute'
        """
        now = timezone.now()
        return JalaliCalendarService.gregorian_to_jalali(now)
    
    @staticmethod
    def format_jalali_date(year, month, day):
        """
        Format Jalali date as string.
        
        Args:
            year (int): Jalali year
            month (int): Jalali month
            day (int): Jalali day
        
        Returns:
            str: Formatted date string (YYYY/MM/DD)
        """
        return f"{year:04d}/{month:02d}/{day:02d}"

