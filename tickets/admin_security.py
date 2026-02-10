"""
Security middleware to restrict Django admin access to specific superuser only.
This prevents IT managers and other users from accessing Django admin panel.
"""
from django.http import HttpResponseForbidden
from django.contrib.auth import get_user_model
from django.utils.deprecation import MiddlewareMixin
from django.utils.translation import gettext_lazy as _

# Import normalization utility (use try/except to avoid circular imports)
try:
    from .utils import normalize_national_id, normalize_employee_code
except ImportError:
    # Fallback during migrations or if utils not available
    def normalize_national_id(value):
        return str(value) if value else ''
    def normalize_employee_code(value):
        return str(value) if value else ''

User = get_user_model()

# Admin superuser credentials (hardcoded for security)
# Only this username can access /admin panel
ADMIN_SUPERUSER_USERNAME = 'iTpArgaSI1rRanTtP'
ADMIN_SUPERUSER_NATIONAL_ID = '3689348171'
ADMIN_SUPERUSER_EMPLOYEE_CODE = '9437'


def is_admin_superuser(user):
    """Check if a user is the admin superuser"""
    if not user or not user.is_authenticated:
        return False
    
    # Normalize identifiers for comparison (handles Persian/Arabic numerals)
    user_nid = normalize_national_id(user.national_id) if user.national_id else ''
    user_ec = normalize_employee_code(user.employee_code) if user.employee_code else ''
    
    return (user.username == ADMIN_SUPERUSER_USERNAME or 
            user_nid == ADMIN_SUPERUSER_NATIONAL_ID or
            user_ec == ADMIN_SUPERUSER_EMPLOYEE_CODE)


def get_admin_superuser_queryset_filter():
    """Get Q object to exclude admin superuser from querysets"""
    from django.db.models import Q
    # Note: Since User.save() normalizes national_id and employee_code,
    # the database values should already be normalized, so direct comparison should work.
    # However, we normalize the constants here for extra safety.
    normalized_nid = normalize_national_id(ADMIN_SUPERUSER_NATIONAL_ID)
    normalized_ec = normalize_employee_code(ADMIN_SUPERUSER_EMPLOYEE_CODE)
    return ~Q(username=ADMIN_SUPERUSER_USERNAME) & ~Q(national_id=normalized_nid) & ~Q(employee_code=normalized_ec)


class AdminAccessRestrictionMiddleware(MiddlewareMixin):
    """
    Middleware to restrict Django admin access.
    Only allows access to the specific superuser account.
    Blocks all other users including IT managers, even if they are superusers.
    
    This ensures that even if an IT manager account is compromised,
    the attacker cannot access Django admin panel.
    """
    
    def process_request(self, request):
        # Check if the request is for admin panel
        if request.path.startswith('/admin/'):
            # Allow access only if user is authenticated and is the specific superuser
            if not request.user.is_authenticated:
                # Let Django handle authentication redirect
                return None
            
            # Check if user is the specific admin superuser (by username, national_id, or employee_code)
            if is_admin_superuser(request.user):
                # Verify the user is actually a superuser
                if request.user.is_superuser and request.user.is_staff:
                    return None
                else:
                    return HttpResponseForbidden(
                        '<html><head><title>403 Forbidden</title></head><body>'
                        '<h1>403 Forbidden</h1>'
                        '<p>Access denied. This account does not have admin privileges.</p>'
                        '</body></html>'
                    )
            else:
                # Block all other users (including IT managers and other superusers)
                return HttpResponseForbidden(
                    '<html><head><title>403 Forbidden</title></head><body>'
                    '<h1>403 Forbidden</h1>'
                    '<p>Access to Django admin panel is restricted.</p>'
                    '<p>Only the system administrator can access this area.</p>'
                    '<p>If you need admin access, please contact the system administrator.</p>'
                    '</body></html>'
                )
        
        return None

