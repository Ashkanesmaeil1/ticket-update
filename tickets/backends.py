from django.contrib.auth.backends import BaseBackend, ModelBackend
from .models import User
from .utils import normalize_national_id, normalize_employee_code, log_authentication_attempt
import logging

logger = logging.getLogger(__name__)

class NationalIDEmployeeCodeBackend(BaseBackend):
    """Custom backend for authenticating with national_id and employee_code"""
    def authenticate(self, request, national_id=None, employee_code=None, password=None, **kwargs):
        # Only authenticate if national_id and employee_code are provided
        if not national_id or not employee_code:
            return None
        
        # Strip whitespace (including copy-paste hidden spaces) before normalization
        national_id = (national_id or '').strip()
        employee_code = (employee_code or '').strip()
        if not national_id or not employee_code:
            return None
        
        # Normalize identifiers to handle Persian/Arabic numerals (Docker locale-safe)
        normalized_national_id = normalize_national_id(national_id)
        normalized_employee_code = normalize_employee_code(employee_code)
        
        # Log the authentication attempt
        logger.debug(
            f"Authentication attempt: National ID='{national_id}' (normalized: '{normalized_national_id}'), "
            f"Employee Code='{employee_code}' (normalized: '{normalized_employee_code}')"
        )
        
        try:
            # Query with normalized values
            user = User.objects.get(national_id=normalized_national_id, employee_code=normalized_employee_code)
            
            # Check if user is active
            if not user.is_active:
                log_authentication_attempt(
                    national_id=normalized_national_id,
                    employee_code=normalized_employee_code,
                    success=False,
                    error_type='inactive_user',
                    error_message='User account is inactive'
                )
                return None
            
            # Log successful authentication
            log_authentication_attempt(
                national_id=normalized_national_id,
                employee_code=normalized_employee_code,
                success=True,
                user_id=user.id
            )
            
            return user
            
        except User.DoesNotExist:
            # User not found - log the failure
            log_authentication_attempt(
                national_id=normalized_national_id,
                employee_code=normalized_employee_code,
                success=False,
                error_type='user_not_found',
                error_message=f'No user found with National ID={normalized_national_id} and Employee Code={normalized_employee_code}'
            )
            
            # Additional debugging: check if user exists with either identifier
            try:
                user_by_nid = User.objects.get(national_id=normalized_national_id)
                logger.warning(
                    f"User found with National ID '{normalized_national_id}' but Employee Code mismatch. "
                    f"Expected: '{normalized_employee_code}', Found: '{user_by_nid.employee_code}'"
                )
            except User.DoesNotExist:
                pass
            
            try:
                user_by_ec = User.objects.get(employee_code=normalized_employee_code)
                logger.warning(
                    f"User found with Employee Code '{normalized_employee_code}' but National ID mismatch. "
                    f"Expected: '{normalized_national_id}', Found: '{user_by_ec.national_id}'"
                )
            except User.DoesNotExist:
                pass
            
            return None
        except Exception as e:
            # Log unexpected errors
            logger.error(
                f"Unexpected error during authentication: {str(e)}",
                exc_info=True,
                extra={
                    'national_id': normalized_national_id,
                    'employee_code': normalized_employee_code
                }
            )
            return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


class AdminModelBackend(ModelBackend):
    """Custom ModelBackend that works with the custom User model for Django admin.
    Username is kept in sync with national_id via User.save(); normalize input for
    Persian/Arabic digits and leading/trailing spaces so admin login matches DB."""
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get('username')
        if username is None or password is None:
            return None
        # Strip and normalize so admin login works with national_id (including Persian digits)
        username = (username or '').strip()
        if not username:
            return None
        normalized_username = normalize_national_id(username)
        try:
            # Look up by username (synced to national_id) or by national_id as fallback
            user = User.objects.filter(username=normalized_username).first()
            if user is None:
                user = User.objects.filter(national_id=normalized_username).first()
            if user is None and normalized_username != username:
                user = User.objects.filter(username=username).first() or User.objects.filter(national_id=username).first()
            if user and user.check_password(password) and self.user_can_authenticate(user):
                return user
        except User.DoesNotExist:
            # Run the default password hasher once to reduce the timing
            # difference between an existing and a non-existing user
            User().set_password(password)
        return None