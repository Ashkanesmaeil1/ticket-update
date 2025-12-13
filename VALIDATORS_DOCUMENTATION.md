# Iranian National ID and Mobile Number Validators

This document provides comprehensive information about the Iranian National ID and Mobile Number validators implemented in the Django project.

## Overview

The validators are located in `tickets/validators.py` and provide robust validation for:
1. **Iranian National ID (کد ملی)** - Validates according to the official Iranian algorithm
2. **Iranian Mobile Number** - Validates Iranian mobile phone numbers

## Iranian National ID Validator

### Features
- **Exact 10 digits**: Must be exactly 10 digits long
- **Check digit validation**: Uses the official Iranian algorithm to validate the last digit
- **Format cleaning**: Automatically removes spaces, dashes, and other non-digit characters
- **Leading zeros preserved**: Maintains leading zeros as they are significant
- **Rejects obvious fakes**: Rejects all-zero codes

### Algorithm
The check digit validation uses the official Iranian algorithm:
1. Multiply each of the first 9 digits by its position weight (10, 9, 8, 7, 6, 5, 4, 3, 2)
2. Sum all products
3. Calculate remainder when divided by 11
4. If remainder < 2, check digit should be remainder
5. If remainder >= 2, check digit should be (11 - remainder)

### Usage Examples

#### In Models
```python
from tickets.validators import validate_iranian_national_id

class User(AbstractUser):
    national_id = models.CharField(
        max_length=20, 
        unique=True, 
        validators=[validate_iranian_national_id]
    )
```

#### In Forms
```python
from tickets.validators import validate_iranian_national_id

class MyForm(forms.Form):
    national_id = forms.CharField(
        validators=[validate_iranian_national_id],
        widget=forms.TextInput(attrs={'placeholder': 'کد ملی ۱۰ رقمی را وارد کنید'})
    )
    
    def clean_national_id(self):
        national_id = self.cleaned_data.get('national_id')
        if national_id:
            return validate_iranian_national_id(national_id)
        return national_id
```

#### Direct Function Call
```python
from tickets.validators import validate_iranian_national_id

try:
    cleaned_id = validate_iranian_national_id('0013542419')
    print(f"Valid National ID: {cleaned_id}")
except ValidationError as e:
    print(f"Invalid National ID: {e}")
```

### Valid Examples
- `1111111111` (all 1s with correct check digit)
- `2222222222` (all 2s with correct check digit)
- `0013542419` (real example with correct check digit)

### Invalid Examples
- `1111111110` (wrong check digit)
- `123456789` (too short)
- `12345678901` (too long)
- `0000000000` (all zeros)
- `123456789a` (contains letters)

## Iranian Mobile Number Validator

### Features
- **Exact 11 digits**: Must be exactly 11 digits long
- **Valid prefix**: Must start with '09'
- **Valid prefixes**: Supports all Iranian mobile prefixes (091, 092, 093, 094, 095, 096, 097, 098, 099)
- **Format cleaning**: Automatically removes spaces, dashes, and other non-digit characters
- **Only digits**: Rejects any non-numeric characters

### Usage Examples

#### In Models
```python
from tickets.validators import validate_iranian_mobile_number

class User(AbstractUser):
    phone = models.CharField(
        max_length=15, 
        blank=True, 
        null=True, 
        validators=[validate_iranian_mobile_number]
    )
```

#### In Forms
```python
from tickets.validators import validate_iranian_mobile_number

class MyForm(forms.Form):
    phone = forms.CharField(
        required=False,
        validators=[validate_iranian_mobile_number],
        widget=forms.TextInput(attrs={'placeholder': 'شماره موبایل را وارد کنید (مثال: 09123456789)'})
    )
    
    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            return validate_iranian_mobile_number(phone)
        return phone
```

#### Direct Function Call
```python
from tickets.validators import validate_iranian_mobile_number

try:
    cleaned_phone = validate_iranian_mobile_number('09123456789')
    print(f"Valid Mobile: {cleaned_phone}")
except ValidationError as e:
    print(f"Invalid Mobile: {e}")
```

### Valid Examples
- `09123456789`
- `09234567890`
- `09345678901`
- `09456789012`
- `09567890123`
- `09678901234`
- `09789012345`
- `09890123456`
- `09901234567`

### Invalid Examples
- `08123456789` (wrong prefix)
- `0912345678` (too short)
- `091234567890` (too long)
- `0912345678a` (contains letters)
- `00123456789` (wrong prefix)

## Error Messages

All error messages are in Persian (Farsi) and include:

### National ID Errors
- `کد ملی باید دقیقاً ۱۰ رقم باشد.` - Must be exactly 10 digits
- `کد ملی نمی‌تواند همه صفر باشد.` - Cannot be all zeros
- `کد ملی نامعتبر است. رقم کنترل صحیح نمی‌باشد.` - Invalid check digit

### Mobile Number Errors
- `شماره موبایل باید دقیقاً ۱۱ رقم باشد.` - Must be exactly 11 digits
- `شماره موبایل باید با ۰۹ شروع شود.` - Must start with 09
- `شماره موبایل باید فقط شامل اعداد باشد.` - Must contain only digits
- `شماره موبایل با پیش‌شماره معتبر شروع نمی‌شود.` - Invalid prefix

## Testing

Comprehensive unit tests are available in `tickets/tests.py`:

### Running Tests
```bash
# Run all validator tests
python manage.py test tickets.tests

# Run specific test classes
python manage.py test tickets.tests.IranianNationalIDValidatorTest
python manage.py test tickets.tests.IranianMobileNumberValidatorTest
python manage.py test tickets.tests.FormValidationTest
python manage.py test tickets.tests.ModelValidationTest
```

### Test Coverage
- Valid National ID validation
- Invalid National ID rejection
- Check digit algorithm testing
- Format cleaning (spaces, dashes)
- Valid Mobile Number validation
- Invalid Mobile Number rejection
- Form integration testing
- Model field validation testing

## Integration with Django

### Model Fields
The validators are already integrated into the User model:
- `national_id` field uses `validate_iranian_national_id`
- `phone` field uses `validate_iranian_mobile_number`

### Forms
The validators are integrated into:
- `EmployeeCreationForm`
- `TechnicianCreationForm`
- `UserCreationByManagerForm`

### Custom Forms
To use in your own forms:

```python
from tickets.validators import validate_iranian_national_id, validate_iranian_mobile_number

class CustomForm(forms.Form):
    national_id = forms.CharField(
        label='کد ملی',
        validators=[validate_iranian_national_id],
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    
    phone = forms.CharField(
        label='شماره موبایل',
        required=False,
        validators=[validate_iranian_mobile_number],
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    
    def clean_national_id(self):
        national_id = self.cleaned_data.get('national_id')
        if national_id:
            return validate_iranian_national_id(national_id)
        return national_id
    
    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            return validate_iranian_mobile_number(phone)
        return phone
```

## Security Considerations

1. **Input Sanitization**: Validators automatically clean input by removing non-digit characters
2. **Format Preservation**: Leading zeros are preserved for National IDs
3. **Algorithm Accuracy**: Uses the official Iranian National ID algorithm
4. **Comprehensive Validation**: Multiple layers of validation ensure data integrity

## Performance

- **Efficient**: Validators use optimized algorithms
- **Lightweight**: Minimal computational overhead
- **Cached**: Django's validation system caches results appropriately

## Maintenance

### Adding New Validators
To add new validators, follow the pattern in `tickets/validators.py`:

```python
def validate_new_field(value):
    """Validate new field according to rules"""
    # Validation logic here
    if not valid:
        raise ValidationError(_('Error message in Persian'))
    return cleaned_value
```

### Updating Error Messages
All error messages are translatable using Django's internationalization system:

```python
from django.utils.translation import gettext_lazy as _

raise ValidationError(_('کد ملی نامعتبر است.'))
```

## Troubleshooting

### Common Issues

1. **Migration Errors**: If you get serialization errors, use function validators instead of class validators
2. **Import Errors**: Ensure validators are imported correctly in your models/forms
3. **Test Failures**: Check that test data uses valid National IDs with correct check digits

### Debugging

To debug validation issues:

```python
from tickets.validators import validate_iranian_national_id, _validate_national_id_check_digit

# Test check digit algorithm directly
print(_validate_national_id_check_digit('1111111111'))  # Should return True

# Test full validation
try:
    result = validate_iranian_national_id('1111111111')
    print(f"Valid: {result}")
except ValidationError as e:
    print(f"Invalid: {e}")
```

## Future Enhancements

Potential improvements:
1. **Additional National ID patterns**: Support for special National ID formats
2. **Enhanced Mobile validation**: Support for landline numbers
3. **Internationalization**: Support for other country formats
4. **Performance optimization**: Caching for frequently used validations 