"""
Utility functions for the tickets app.
Includes normalization utilities for handling Persian/Arabic numerals.
"""
import logging
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

# Persian/Arabic to English numeral mapping
PERSIAN_TO_ENGLISH = {
    '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
    '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
    # Arabic-Indic numerals (alternative forms)
    '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
    '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
}

# Reverse mapping for English to Persian (if needed for display)
ENGLISH_TO_PERSIAN = {v: k for k, v in PERSIAN_TO_ENGLISH.items() if ord(k) < 0x1000}


def normalize_numeric_string(value):
    """
    Normalize a numeric string by:
    1. Converting Persian/Arabic numerals to English numerals
    2. Stripping whitespace
    3. Removing any non-digit characters (except for validation purposes)
    
    Args:
        value: String or numeric value to normalize
        
    Returns:
        str: Normalized string with only English digits, or empty string if invalid
        
    Example:
        normalize_numeric_string('۱۲۳۴') -> '1234'
        normalize_numeric_string('1234') -> '1234'
        normalize_numeric_string(' ۱۲۳۴ ') -> '1234'
    """
    if value is None:
        return ''
    
    # Convert to string
    str_value = str(value).strip()
    
    if not str_value:
        return ''
    
    # Convert Persian/Arabic numerals to English
    normalized = ''
    for char in str_value:
        if char in PERSIAN_TO_ENGLISH:
            normalized += PERSIAN_TO_ENGLISH[char]
        elif char.isdigit():
            normalized += char
        elif char.isspace():
            # Skip whitespace
            continue
        else:
            # For non-digit, non-whitespace characters, preserve them
            # This allows for formats like "123-456" if needed
            normalized += char
    
    return normalized


def normalize_national_id(value):
    """
    Normalize National ID (کد ملی) by converting to English digits and stripping whitespace.
    
    Args:
        value: National ID value to normalize
        
    Returns:
        str: Normalized National ID with only English digits
        
    Example:
        normalize_national_id('۱۲۳۴۵۶۷۸۹۰') -> '1234567890'
    """
    normalized = normalize_numeric_string(value)
    
    # Log normalization if conversion occurred
    if value and str(value) != normalized:
        logger.debug(
            f"National ID normalized: '{value}' -> '{normalized}'",
            extra={'original': str(value), 'normalized': normalized}
        )
    
    return normalized


def normalize_employee_code(value):
    """
    Normalize Employee Code (کد کارمندی) by converting to English digits and stripping whitespace.
    
    Args:
        value: Employee code value to normalize
        
    Returns:
        str: Normalized Employee Code with only English digits
        
    Example:
        normalize_employee_code('۱۲۳۴') -> '1234'
    """
    normalized = normalize_numeric_string(value)
    
    # Log normalization if conversion occurred
    if value and str(value) != normalized:
        logger.debug(
            f"Employee Code normalized: '{value}' -> '{normalized}'",
            extra={'original': str(value), 'normalized': normalized}
        )
    
    return normalized


def log_authentication_attempt(national_id, employee_code, success=False, user_id=None, error_type=None, error_message=None):
    """
    Log authentication attempts for debugging and security auditing.
    
    Args:
        national_id: The National ID used in the attempt
        employee_code: The Employee Code used in the attempt
        success: Whether authentication was successful
        user_id: The user ID if authentication succeeded
        error_type: Type of error ('user_not_found', 'inactive_user', 'invalid_credentials', etc.)
        error_message: Detailed error message
    """
    log_data = {
        'national_id': national_id,
        'employee_code': employee_code,
        'success': success,
        'user_id': user_id,
        'error_type': error_type,
        'error_message': error_message,
    }
    
    if success:
        logger.info(
            f"Authentication successful: National ID={national_id}, Employee Code={employee_code}, User ID={user_id}",
            extra=log_data
        )
    else:
        logger.warning(
            f"Authentication failed: National ID={national_id}, Employee Code={employee_code}, "
            f"Error Type={error_type}, Error={error_message}",
            extra=log_data
        )





