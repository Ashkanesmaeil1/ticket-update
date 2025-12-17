"""
Jalali Calendar Service

This service handles all interaction with the external calendar API (https://pnldev.com/api/calender)
and manages caching of calendar data in the database.

Architecture: Frontend NEVER calls external API directly. All API calls go through this service.
"""

import requests
import logging
from typing import Dict, List, Optional
from django.utils import timezone
from django.db import transaction
from ..models import CalendarDay

logger = logging.getLogger(__name__)

# API Configuration
CALENDAR_API_URL = 'https://pnldev.com/api/calender'
API_TIMEOUT = 10  # seconds


def fetch_and_cache_month_data(year: int, month: int) -> List[Dict]:
    """
    Fetch calendar data from external API for a specific year/month and cache it in the database.
    
    Args:
        year: Jalali year (e.g., 1403)
        month: Jalali month (1-12)
    
    Returns:
        List of dictionaries containing day data for the month
    
    Raises:
        requests.RequestException: If API request fails
        ValueError: If API response is invalid
    """
    try:
        # Make API request
        params = {
            'year': year,
            'month': month
        }
        
        logger.info(f"Fetching calendar data from API: year={year}, month={month}")
        response = requests.get(CALENDAR_API_URL, params=params, timeout=API_TIMEOUT)
        response.raise_for_status()  # Raise exception for bad status codes
        
        # Parse JSON response
        data = response.json()
        
        # API returns: {"status": true, "result": {"1": {...day data...}, "2": {...}, ...}}
        days_dict = None
        if isinstance(data, dict):
            if 'result' in data and isinstance(data['result'], dict):
                days_dict = data['result']
            elif 'data' in data and isinstance(data['data'], dict):
                days_dict = data['data']
            elif 'days' in data and isinstance(data['days'], dict):
                days_dict = data['days']
            else:
                # Check if the dict itself contains day keys (numeric strings)
                if all(str(k).isdigit() for k in data.keys() if k != 'status'):
                    days_dict = {k: v for k, v in data.items() if k != 'status'}
        elif isinstance(data, list):
            # If it's a list, convert to dict format
            days_dict = {str(i+1): day for i, day in enumerate(data)}
        
        if days_dict is None:
            raise ValueError(f"Invalid API response format. Expected dict with 'result' key. Got: {type(data)} with keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
        
        logger.info(f"Processing {len(days_dict)} days from API response")
        
        # Cache each day's data in the database
        cached_days = []
        with transaction.atomic():
            for day_key, day_data in days_dict.items():
                try:
                    # Extract day information from API format
                    # API format: {"solar": {"day": 1, "month": 9, "year": 1403}, "gregorian": {"day": 21, "month": 11, "year": 2024}, "holiday": false, "event": [...]}
                    solar = day_data.get('solar', {})
                    gregorian = day_data.get('gregorian', {})
                    
                    day_number = solar.get('day') or day_data.get('day')
                    if day_number is None:
                        # Try to parse from key
                        try:
                            day_number = int(day_key)
                        except (ValueError, TypeError):
                            logger.warning(f"Could not determine day number for day_key: {day_key}")
                            continue
                    
                    # Format dates
                    solar_date = f"{solar.get('year', year)}/{solar.get('month', month):02d}/{day_number:02d}" if solar else ''
                    gregorian_date = f"{gregorian.get('year', '')}-{gregorian.get('month', ''):02d}-{gregorian.get('day', ''):02d}" if gregorian else ''
                    
                    is_holiday = day_data.get('holiday', False) or day_data.get('is_holiday', False)
                    events = day_data.get('event', []) or day_data.get('events', [])
                    
                    if day_number is None:
                        logger.warning(f"Skipping day data without day number: {day_data}")
                        continue
                    
                    # Update or create calendar day
                    calendar_day, created = CalendarDay.objects.update_or_create(
                        year=year,
                        month=month,
                        day=day_number,
                        defaults={
                            'solar_date': solar_date,
                            'gregorian_date': gregorian_date,
                            'is_holiday': is_holiday,
                            'events_json': events,
                        }
                    )
                    
                    cached_days.append({
                        'year': calendar_day.year,
                        'month': calendar_day.month,
                        'day': calendar_day.day,
                        'solar_date': calendar_day.solar_date,
                        'gregorian_date': calendar_day.gregorian_date,
                        'is_holiday': calendar_day.is_holiday,
                        'events': calendar_day.events_json,
                    })
                    
                except Exception as e:
                    logger.error(f"Error caching day data: {day_data}, error: {e}", exc_info=True)
                    continue
        
        logger.info(f"Successfully cached {len(cached_days)} days for {year}/{month}")
        return cached_days
        
    except requests.Timeout:
        logger.error(f"API request timeout for year={year}, month={month}")
        raise requests.RequestException("API request timed out")
    except requests.RequestException as e:
        logger.error(f"API request failed for year={year}, month={month}: {e}")
        raise
    except ValueError as e:
        logger.error(f"Invalid API response for year={year}, month={month}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching calendar data for year={year}, month={month}: {e}", exc_info=True)
        raise


def get_or_fetch_month_data(year: int, month: int) -> List[Dict]:
    """
    Get calendar data for a specific year/month from cache or fetch from API if not cached.
    
    Args:
        year: Jalali year (e.g., 1403)
        month: Jalali month (1-12)
    
    Returns:
        List of dictionaries containing day data for the month
    """
    # First, try to get from cache
    cached_days = CalendarDay.objects.filter(year=year, month=month).order_by('day')
    
    if cached_days.exists():
        # Cache hit - return cached data
        logger.debug(f"Cache hit for year={year}, month={month}")
        return [
            {
                'year': day.year,
                'month': day.month,
                'day': day.day,
                'solar_date': day.solar_date,
                'gregorian_date': day.gregorian_date,
                'is_holiday': day.is_holiday,
                'events': day.events_json,
            }
            for day in cached_days
        ]
    else:
        # Cache miss - fetch from API and cache
        logger.info(f"Cache miss for year={year}, month={month}, fetching from API")
        try:
            return fetch_and_cache_month_data(year, month)
        except Exception as e:
            logger.error(f"Failed to fetch calendar data for year={year}, month={month}: {e}")
            # Return empty list if API fails - frontend should handle gracefully
            return []


def clear_month_cache(year: int, month: int) -> int:
    """
    Clear cached data for a specific year/month.
    
    Args:
        year: Jalali year
        month: Jalali month
    
    Returns:
        Number of deleted records
    """
    deleted_count, _ = CalendarDay.objects.filter(year=year, month=month).delete()
    logger.info(f"Cleared {deleted_count} cached days for year={year}, month={month}")
    return deleted_count

