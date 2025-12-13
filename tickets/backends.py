from django.contrib.auth.backends import BaseBackend, ModelBackend
from .models import User

class NationalIDEmployeeCodeBackend(BaseBackend):
    """Custom backend for authenticating with national_id and employee_code"""
    def authenticate(self, request, national_id=None, employee_code=None, password=None, **kwargs):
        # Only authenticate if national_id and employee_code are provided
        if not national_id or not employee_code:
            return None
            
        try:
            user = User.objects.get(national_id=national_id, employee_code=employee_code)
            # Optionally check password if you want to require it
            # if password and not user.check_password(password):
            #     return None
            if user.is_active:
                return user
        except User.DoesNotExist:
            return None
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


class AdminModelBackend(ModelBackend):
    """Custom ModelBackend that works with the custom User model for Django admin"""
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get('username')
        if username is None or password is None:
            return None
        try:
            # Try to get user by username (even though it's not unique, get the first match)
            user = User.objects.filter(username=username).first()
            if user and user.check_password(password) and self.user_can_authenticate(user):
                return user
        except User.DoesNotExist:
            # Run the default password hasher once to reduce the timing
            # difference between an existing and a non-existing user
            User().set_password(password)
        return None