"""
Signal handlers for automatically logging ticket activities
"""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _
from .models import Ticket, Reply, TicketActivityLog


# Store original values before save to detect changes
_ticket_original_values = {}


@receiver(pre_save, sender=Ticket)
def store_ticket_original_values(sender, instance, **kwargs):
    """Store original ticket values before save to detect changes"""
    if instance.pk:
        try:
            original = Ticket.objects.get(pk=instance.pk)
            _ticket_original_values[instance.pk] = {
                'status': original.status,
                'priority': original.priority,
                'assigned_to_id': original.assigned_to_id if original.assigned_to else None,
                'access_approval_status': original.access_approval_status,
            }
        except Ticket.DoesNotExist:
            pass


@receiver(post_save, sender=Ticket)
def log_ticket_changes(sender, instance, created, **kwargs):
    """Log all changes to tickets"""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    # Get the user who made the change (if available from request thread)
    # We'll use a thread-local storage or pass user through save() method
    # For now, we'll try to get it from the instance if it was set
    user = getattr(instance, '_activity_user', None)
    
    if created:
        # Log ticket creation
        TicketActivityLog.objects.create(
            ticket=instance,
            user=instance.created_by if instance.created_by else user,
            action='created',
            description=_('تیکت ایجاد شد'),
            new_value=instance.title
        )
    else:
        # Log changes to existing ticket
        original = _ticket_original_values.get(instance.pk, {})
        
        # Status change
        if original.get('status') and original['status'] != instance.status:
            from .services import get_status_display_persian
            old_status = get_status_display_persian(original['status'])
            new_status = get_status_display_persian(instance.status)
            # Ensure we have a user - fallback to created_by if _activity_user is not set
            log_user = user if user else (instance.created_by if hasattr(instance, 'created_by') else None)
            TicketActivityLog.objects.create(
                ticket=instance,
                user=log_user,
                action='status_changed',
                description=_('وضعیت تیکت تغییر کرد'),
                old_value=old_status,
                new_value=new_status
            )
        
        # Priority change
        if original.get('priority') and original['priority'] != instance.priority:
            priority_display = dict(Ticket.PRIORITY_CHOICES)
            old_priority = priority_display.get(original['priority'], original['priority'])
            new_priority = priority_display.get(instance.priority, instance.priority)
            # Ensure we have a user - fallback to created_by if _activity_user is not set
            log_user = user if user else (instance.created_by if hasattr(instance, 'created_by') else None)
            TicketActivityLog.objects.create(
                ticket=instance,
                user=log_user,
                action='priority_changed',
                description=_('اولویت تیکت تغییر کرد'),
                old_value=old_priority,
                new_value=new_priority
            )
        
        # Assignment change
        old_assigned_id = original.get('assigned_to_id')
        new_assigned_id = instance.assigned_to_id if instance.assigned_to else None
        
        if old_assigned_id != new_assigned_id:
            if new_assigned_id:
                try:
                    assigned_user = User.objects.get(pk=new_assigned_id)
                    assigned_name = assigned_user.get_full_name() or assigned_user.username
                except User.DoesNotExist:
                    assigned_name = _('نامشخص')
                
                # Ensure we have a user - fallback to created_by if _activity_user is not set
                log_user = user if user else (instance.created_by if hasattr(instance, 'created_by') else None)
                TicketActivityLog.objects.create(
                    ticket=instance,
                    user=log_user,
                    action='assigned',
                    description=_('تیکت تخصیص داده شد'),
                    new_value=assigned_name
                )
            else:
                # Ensure we have a user - fallback to created_by if _activity_user is not set
                log_user = user if user else (instance.created_by if hasattr(instance, 'created_by') else None)
                TicketActivityLog.objects.create(
                    ticket=instance,
                    user=log_user,
                    action='unassigned',
                    description=_('تخصیص تیکت حذف شد'),
                    old_value=_('تخصیص داده شده') if old_assigned_id else ''
                )
        
        # Access approval status change
        if original.get('access_approval_status') and original['access_approval_status'] != instance.access_approval_status:
            approval_display = dict(Ticket.ACCESS_APPROVAL_CHOICES)
            old_approval = approval_display.get(original['access_approval_status'], original['access_approval_status'])
            new_approval = approval_display.get(instance.access_approval_status, instance.access_approval_status)
            
            action = 'access_approved' if instance.access_approval_status == 'approved' else 'access_rejected' if instance.access_approval_status == 'rejected' else 'updated'
            
            # Ensure we have a user - fallback to created_by if _activity_user is not set
            log_user = user if user else (instance.created_by if hasattr(instance, 'created_by') else None)
            TicketActivityLog.objects.create(
                ticket=instance,
                user=log_user,
                action=action,
                description=_('وضعیت تایید دسترسی شبکه تغییر کرد'),
                old_value=old_approval,
                new_value=new_approval
            )
        
        # Clear stored original values
        if instance.pk in _ticket_original_values:
            del _ticket_original_values[instance.pk]


@receiver(post_save, sender=Reply)
def log_reply_creation(sender, instance, created, **kwargs):
    """Log when a reply is added to a ticket"""
    if created:
        # Get the user who made the change (if available from request thread)
        user = getattr(instance, '_activity_user', None) or instance.author
        
        description = _('پاسخ جدید اضافه شد')
        if instance.is_private:
            description = _('پاسخ محرمانه اضافه شد')
        
        TicketActivityLog.objects.create(
            ticket=instance.ticket,
            user=user,
            action='replied',
            description=description,
            new_value=instance.content[:100] + ('...' if len(instance.content) > 100 else ''),
            reply=instance
        )

