from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
import re

# Import normalization utility (use try/except to avoid circular imports during migrations)
try:
    from .utils import normalize_national_id, normalize_employee_code
except ImportError:
    # Fallback during migrations or if utils not available
    def normalize_national_id(value):
        return re.sub(r'[^\d]', '', str(value)) if value else ''
    def normalize_employee_code(value):
        return re.sub(r'[^\d]', '', str(value)) if value else ''


def validate_iranian_national_id(value):
    """
    Validates Iranian National ID (کد ملی) according to official algorithm.
    
    Rules:
    - Must be exactly 10 digits
    - Last digit is a check digit calculated using the official algorithm
    - Rejects obviously fake codes like all zeros
    - Only digits allowed (Persian/Arabic numerals are normalized to English)
    - Leading zeros preserved
    """
    # Normalize Persian/Arabic numerals to English, then remove any non-digit characters
    cleaned_value = normalize_national_id(value)
    
    # Check if it's exactly 10 digits
    if len(cleaned_value) != 10:
        raise ValidationError(_('کد ملی باید دقیقاً ۱۰ رقم باشد.'))
    
    # Check if it's all zeros
    if cleaned_value == '0000000000':
        raise ValidationError(_('کد ملی نمی‌تواند همه صفر باشد.'))
    
    # Validate check digit using official Iranian algorithm
    if not _validate_national_id_check_digit(cleaned_value):
        raise ValidationError(_('کد ملی نامعتبر است. رقم کنترل صحیح نمی‌باشد.'))
    
    return cleaned_value


def _validate_national_id_check_digit(national_id):
    """
    Validates the check digit of Iranian National ID using official algorithm.
    
    Algorithm:
    1. Multiply each digit by its position (10-2 for first 9 digits)
    2. Sum all products
    3. Calculate remainder when divided by 11
    4. If remainder < 2, check digit should be remainder
    5. If remainder >= 2, check digit should be (11 - remainder)
    """
    if len(national_id) != 10:
        return False
    
    # Get the first 9 digits and the check digit
    digits = [int(d) for d in national_id[:9]]
    check_digit = int(national_id[9])
    
    # Calculate weighted sum (positions 10, 9, 8, 7, 6, 5, 4, 3, 2)
    weighted_sum = 0
    for i, digit in enumerate(digits):
        weighted_sum += digit * (10 - i)
    
    # Calculate remainder
    remainder = weighted_sum % 11
    
    # Determine expected check digit
    if remainder < 2:
        expected_check_digit = remainder
    else:
        expected_check_digit = 11 - remainder
    
    return check_digit == expected_check_digit


def validate_iranian_mobile_number(value):
    """
    Validates Iranian mobile phone number.
    
    Rules:
    - Must be exactly 11 digits
    - Must start with '09'
    - Only digits allowed
    - Valid Iranian mobile number format
    """
    # Keep parity with frontend format:
    # /(^(0?9)|(\+?989))\d{2}\W?\d{3}\W?\d{4}/g
    raw_value = str(value).strip()
    mobile_pattern = re.compile(r'(^(0?9)|(\+?989))\d{2}\W?\d{3}\W?\d{4}$')

    if not mobile_pattern.fullmatch(raw_value):
        raise ValidationError(_('شماره موبایل نامعتبر است.'))

    # Normalize stored value to canonical local format: 09XXXXXXXXX
    digits_only = re.sub(r'[^\d]', '', raw_value)
    if digits_only.startswith('989') and len(digits_only) == 12:
        return f"0{digits_only[2:]}"
    if digits_only.startswith('09') and len(digits_only) == 11:
        return digits_only
    if digits_only.startswith('9') and len(digits_only) == 10:
        return f"0{digits_only}"

    raise ValidationError(_('شماره موبایل نامعتبر است.'))


# Regex validators for form fields
iranian_national_id_regex = RegexValidator(
    regex=r'^\d{10}$',
    message=_('کد ملی باید دقیقاً ۱۰ رقم باشد.'),
    code='invalid_national_id'
)

iranian_mobile_regex = RegexValidator(
    regex=r'(^(0?9)|(\+?989))\d{2}\W?\d{3}\W?\d{4}$',
    message=_('شماره موبایل نامعتبر است.'),
    code='invalid_mobile_number'
)


class IranianNationalIDValidator:
    """
    Custom validator class for Iranian National ID.
    Can be used in model fields or forms.
    """
    
    def __call__(self, value):
        validate_iranian_national_id(value)


class IranianMobileNumberValidator:
    """
    Custom validator class for Iranian Mobile Number.
    Can be used in model fields or forms.
    """
    
    def __call__(self, value):
        validate_iranian_mobile_number(value) 