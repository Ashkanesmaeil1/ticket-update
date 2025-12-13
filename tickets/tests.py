from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from .validators import (
    validate_iranian_national_id, 
    validate_iranian_mobile_number,
    _validate_national_id_check_digit
)
from .models import User
from .forms import EmployeeCreationForm, TechnicianCreationForm


class IranianNationalIDValidatorTest(TestCase):
    """Test cases for Iranian National ID validation"""
    
    def test_valid_national_ids(self):
        """Test valid Iranian National IDs"""
        valid_ids = [
            '1111111111',  # Valid check digit (all 1s with correct check digit)
            '2222222222',  # Valid check digit (all 2s with correct check digit)
            '3333333333',  # Valid check digit (all 3s with correct check digit)
            '4444444444',  # Valid check digit (all 4s with correct check digit)
            '5555555555',  # Valid check digit (all 5s with correct check digit)
        ]
        
        for national_id in valid_ids:
            try:
                result = validate_iranian_national_id(national_id)
                self.assertEqual(result, national_id)
            except ValidationError as e:
                self.fail(f"Valid national ID {national_id} failed validation: {e}")
    
    def test_invalid_national_ids(self):
        """Test invalid Iranian National IDs"""
        invalid_ids = [
            '1111111110',  # Invalid check digit
            '2222222221',  # Invalid check digit
            '123456789',   # Too short
            '12345678901', # Too long
            '0000000000',  # All zeros
            '123456789a',  # Contains letter
            '123456789-',  # Contains dash
            '123456789 ',  # Contains space
        ]
        
        for national_id in invalid_ids:
            with self.assertRaises(ValidationError):
                validate_iranian_national_id(national_id)
    
    def test_national_id_with_spaces_and_dashes(self):
        """Test that spaces and dashes are properly removed"""
        test_cases = [
            ('1111111111', '1111111111'),
            ('111-111-1111', '1111111111'),
            ('111 111 1111', '1111111111'),
            ('111-111-1111', '1111111111'),
        ]
        
        for input_id, expected in test_cases:
            result = validate_iranian_national_id(input_id)
            self.assertEqual(result, expected)
    
    def test_check_digit_algorithm(self):
        """Test the check digit validation algorithm"""
        # Test valid check digits
        self.assertTrue(_validate_national_id_check_digit('1111111111'))
        self.assertTrue(_validate_national_id_check_digit('2222222222'))
        self.assertTrue(_validate_national_id_check_digit('3333333333'))
        
        # Test invalid check digits
        self.assertFalse(_validate_national_id_check_digit('1111111110'))
        self.assertFalse(_validate_national_id_check_digit('2222222221'))
        self.assertFalse(_validate_national_id_check_digit('3333333332'))


class IranianMobileNumberValidatorTest(TestCase):
    """Test cases for Iranian Mobile Number validation"""
    
    def test_valid_mobile_numbers(self):
        """Test valid Iranian mobile numbers"""
        valid_numbers = [
            '09123456789',
            '09234567890',
            '09345678901',
            '09456789012',
            '09567890123',
            '09678901234',
            '09789012345',
            '09890123456',
            '09901234567',
        ]
        
        for mobile in valid_numbers:
            try:
                result = validate_iranian_mobile_number(mobile)
                self.assertEqual(result, mobile)
            except ValidationError as e:
                self.fail(f"Valid mobile number {mobile} failed validation: {e}")
    
    def test_invalid_mobile_numbers(self):
        """Test invalid Iranian mobile numbers"""
        invalid_numbers = [
            '08123456789',  # Wrong prefix
            '0912345678',   # Too short
            '091234567890', # Too long
            '0912345678a',  # Contains letter
            '0912345678-',  # Contains dash
            '0912345678 ',  # Contains space
            '00123456789',  # Wrong prefix
            '12345678901',  # No prefix
        ]
        
        for mobile in invalid_numbers:
            with self.assertRaises(ValidationError):
                validate_iranian_mobile_number(mobile)
    
    def test_mobile_with_spaces_and_dashes(self):
        """Test that spaces and dashes are properly removed"""
        test_cases = [
            ('09123456789', '09123456789'),
            ('0912-345-6789', '09123456789'),
            ('0912 345 6789', '09123456789'),
            ('0912-345-6789', '09123456789'),
        ]
        
        for input_mobile, expected in test_cases:
            result = validate_iranian_mobile_number(input_mobile)
            self.assertEqual(result, expected)


class FormValidationTest(TestCase):
    """Test form validation with the new validators"""
    
    def test_employee_form_valid_data(self):
        """Test EmployeeCreationForm with valid data"""
        form_data = {
            'first_name': 'علی',
            'last_name': 'احمدی',
            'email': 'ali@example.com',
            'phone': '09123456789',
            'department': 'فنی',
            'national_id': '1111111111',
            'employee_code': '1234',
            'password1': 'testpass123',
            'password2': 'testpass123',
        }
        
        form = EmployeeCreationForm(data=form_data)
        self.assertTrue(form.is_valid(), f"Form errors: {form.errors}")
    
    def test_employee_form_invalid_national_id(self):
        """Test EmployeeCreationForm with invalid national ID"""
        form_data = {
            'first_name': 'علی',
            'last_name': 'احمدی',
            'email': 'ali@example.com',
            'phone': '09123456789',
            'department': 'فنی',
            'national_id': '1111111110',  # Invalid: wrong check digit
            'employee_code': '1234',
            'password1': 'testpass123',
            'password2': 'testpass123',
        }
        
        form = EmployeeCreationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('national_id', form.errors)
    
    def test_employee_form_invalid_mobile(self):
        """Test EmployeeCreationForm with invalid mobile number"""
        form_data = {
            'first_name': 'علی',
            'last_name': 'احمدی',
            'email': 'ali@example.com',
            'phone': '08123456789',  # Invalid: wrong prefix
            'department': 'فنی',
            'national_id': '1111111111',
            'employee_code': '1234',
            'password1': 'testpass123',
            'password2': 'testpass123',
        }
        
        form = EmployeeCreationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('phone', form.errors)
    
    def test_technician_form_valid_data(self):
        """Test TechnicianCreationForm with valid data"""
        form_data = {
            'first_name': 'رضا',
            'last_name': 'محمدی',
            'email': 'reza@example.com',
            'phone': '09234567890',
            'department': 'فنی',
            'national_id': '2222222222',
            'employee_code': '5678',
            'password1': 'testpass123',
            'password2': 'testpass123',
        }
        
        form = TechnicianCreationForm(data=form_data)
        self.assertTrue(form.is_valid(), f"Form errors: {form.errors}")
    
    def test_form_with_optional_phone(self):
        """Test that phone field is optional"""
        form_data = {
            'first_name': 'علی',
            'last_name': 'احمدی',
            'email': 'ali@example.com',
            'phone': '',  # Empty phone should be valid
            'department': 'فنی',
            'national_id': '1111111111',
            'employee_code': '1234',
            'password1': 'testpass123',
            'password2': 'testpass123',
        }
        
        form = EmployeeCreationForm(data=form_data)
        self.assertTrue(form.is_valid(), f"Form errors: {form.errors}")


class ModelValidationTest(TestCase):
    """Test model field validation"""
    
    def test_user_model_valid_data(self):
        """Test User model with valid data"""
        user_data = {
            'first_name': 'علی',
            'last_name': 'احمدی',
            'email': 'ali@example.com',
            'phone': '09123456789',
            'department': 'فنی',
            'national_id': '1111111111',
            'employee_code': '1234',
            'username': 'user_1111111111',
        }
        
        user = User(**user_data)
        user.set_password('testpass123')
        
        # Should not raise any validation errors
        user.full_clean()
        user.save()
        
        # Verify the user was created
        self.assertEqual(User.objects.count(), 1)
        created_user = User.objects.first()
        self.assertEqual(created_user.national_id, '1111111111')
        self.assertEqual(created_user.phone, '09123456789')
    
    def test_user_model_invalid_national_id(self):
        """Test User model with invalid national ID"""
        user_data = {
            'first_name': 'علی',
            'last_name': 'احمدی',
            'email': 'ali@example.com',
            'phone': '09123456789',
            'department': 'فنی',
            'national_id': '1111111110',  # Invalid
            'employee_code': '1234',
            'username': 'user_1111111110',
        }
        
        user = User(**user_data)
        user.set_password('testpass123')
        
        with self.assertRaises(ValidationError):
            user.full_clean()
    
    def test_user_model_invalid_mobile(self):
        """Test User model with invalid mobile number"""
        user_data = {
            'first_name': 'علی',
            'last_name': 'احمدی',
            'email': 'ali@example.com',
            'phone': '08123456789',  # Invalid prefix
            'department': 'فنی',
            'national_id': '1111111111',
            'employee_code': '1234',
            'username': 'user_1111111111',
        }
        
        user = User(**user_data)
        user.set_password('testpass123')
        
        with self.assertRaises(ValidationError):
            user.full_clean() 