from django import template
from tickets.models import Notification

register = template.Library()

@register.simple_tag(takes_context=True)
def unread_notifications_count(context):
    request = context['request']
    if request.user.is_authenticated and request.user.role == 'it_manager':
        return Notification.objects.filter(recipient=request.user, is_read=False).count()
    return 0

@register.simple_tag(takes_context=True)
def unread_team_leader_notifications_count(context):
    request = context['request']
    if request.user.is_authenticated and request.user.role == 'employee' and request.user.department_role == 'senior':
        return Notification.objects.filter(recipient=request.user, is_read=False, category='team_leader_access').count()
    return 0

@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key"""
    return dictionary.get(key, 0)