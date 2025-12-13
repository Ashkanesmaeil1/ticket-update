from django import template
from ..admin_security import is_admin_superuser

register = template.Library()

@register.filter
def is_admin_superuser_filter(user):
    """Template filter to check if user is admin superuser"""
    return is_admin_superuser(user)


