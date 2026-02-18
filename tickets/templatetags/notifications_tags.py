from django import template
from tickets.models import Notification, LoanRequest

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

@register.simple_tag(takes_context=True)
def pending_loan_requests_count(context):
    """تعداد درخواست‌های امانت در انتظار بررسی برای مدیر IT"""
    request = context['request']
    if request.user.is_authenticated and request.user.role == 'it_manager':
        return LoanRequest.objects.filter(status='pending').count()
    return 0

@register.simple_tag(takes_context=True)
def unseen_loan_updates_count(context):
    """تعداد درخواست‌های امانت کاربر که تایید یا رد شده‌اند ولی هنوز مشاهده نشده‌اند"""
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return 0
    
    # فقط برای کاربران عادی (نه مدیر IT)
    if request.user.role == 'it_manager':
        return 0
    
    try:
        # بررسی وجود فیلد viewed_at در مدل
        if not hasattr(LoanRequest, 'viewed_at'):
            return 0
        
        # شمارش درخواست‌های تایید یا رد شده که هنوز مشاهده نشده‌اند
        # استفاده از Q objects برای اطمینان از درستی query
        from django.db.models import Q
        count = LoanRequest.objects.filter(
            Q(requester=request.user) &
            Q(status__in=['approved', 'rejected']) &
            Q(viewed_at__isnull=True)
        ).count()
        
        # Debug: اگر count > 0 است، badge باید نمایش داده شود
        return count
    except Exception as e:
        # اگر خطایی رخ داد (مثلاً فیلد در دیتابیس وجود ندارد)، 0 برگردان
        # این می‌تواند به دلیل عدم اجرای migration باشد
        return 0

@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key"""
    return dictionary.get(key, 0)