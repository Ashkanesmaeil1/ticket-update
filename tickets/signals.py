"""
Signal handlers for automatically logging ticket activities
"""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _
from django.contrib.sessions.models import Session
from django.utils import timezone
from .models import Ticket, Reply, TicketActivityLog, User
from .utils import normalize_national_id, normalize_employee_code
import logging

logger = logging.getLogger(__name__)


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


# Store original User values before save to detect identifier changes
_user_original_values = {}


@receiver(pre_save, sender=User)
def normalize_user_identifiers(sender, instance, **kwargs):
    """
    Pre-save signal to normalize National ID and Employee Code.
    This ensures normalization happens even when admin bypasses form validation
    or uses direct database updates.
    """
    # Store original values for comparison
    if instance.pk:
        try:
            original = User.objects.get(pk=instance.pk)
            _user_original_values[instance.pk] = {
                'national_id': original.national_id,
                'employee_code': original.employee_code,
            }
        except User.DoesNotExist:
            _user_original_values[instance.pk] = {
                'national_id': None,
                'employee_code': None,
            }
    else:
        _user_original_values[instance.pk] = {
            'national_id': None,
            'employee_code': None,
        }
    
    # Normalize National ID
    if instance.national_id:
        original_nid = instance.national_id
        normalized_nid = normalize_national_id(instance.national_id)
        if original_nid != normalized_nid:
            logger.info(
                f"User {instance.pk or 'new'}: Pre-save signal normalizing National ID "
                f"from '{original_nid}' to '{normalized_nid}'"
            )
            instance.national_id = normalized_nid
    
    # Normalize Employee Code
    if instance.employee_code:
        original_ec = instance.employee_code
        normalized_ec = normalize_employee_code(instance.employee_code)
        if original_ec != normalized_ec:
            logger.info(
                f"User {instance.pk or 'new'}: Pre-save signal normalizing Employee Code "
                f"from '{original_ec}' to '{normalized_ec}'"
            )
            instance.employee_code = normalized_ec


@receiver(post_save, sender=User)
def handle_user_identifier_changes(sender, instance, created, **kwargs):
    """
    Post-save signal to handle identifier changes:
    1. Invalidate all active sessions when National ID or Employee Code changes
    2. Log the changes for audit purposes
    3. Ensure password hash is NOT affected
    """
    original = _user_original_values.get(instance.pk, {})
    
    # Check if identifiers changed
    national_id_changed = (
        original.get('national_id') is not None and
        original.get('national_id') != instance.national_id
    )
    employee_code_changed = (
        original.get('employee_code') is not None and
        original.get('employee_code') != instance.employee_code
    )
    
    if national_id_changed or employee_code_changed:
        logger.warning(
            f"User {instance.pk} ({instance.get_full_name()}): Identifier(s) changed. "
            f"National ID: {original.get('national_id')} -> {instance.national_id}, "
            f"Employee Code: {original.get('employee_code')} -> {instance.employee_code}"
        )
        
        # Invalidate all active sessions for this user
        # This prevents "ghost sessions" with old identifiers from blocking authentication
        try:
            from django.contrib.sessions.models import Session
            
            # Get all non-expired sessions
            active_sessions = Session.objects.filter(expire_date__gte=timezone.now())
            deleted_count = 0
            
            # Iterate through sessions and delete those belonging to this user
            # Note: This is necessary because Django stores user_id in session data,
            # not as a foreign key, so we can't query directly
            for session in active_sessions:
                try:
                    session_data = session.get_decoded()
                    session_user_id = session_data.get('_auth_user_id')
                    
                    # If this session belongs to the user whose identifiers changed, delete it
                    if session_user_id and str(session_user_id) == str(instance.pk):
                        session.delete()
                        deleted_count += 1
                except Exception as e:
                    # Skip sessions that can't be decoded (expired, corrupted, etc.)
                    logger.debug(f"Could not decode session {session.session_key}: {e}")
                    continue
            
            if deleted_count > 0:
                logger.info(
                    f"User {instance.pk}: Invalidated {deleted_count} active session(s) "
                    f"due to identifier change (National ID or Employee Code changed)"
                )
            else:
                logger.debug(f"User {instance.pk}: No active sessions to invalidate")
        except Exception as e:
            logger.error(
                f"Error invalidating sessions for user {instance.pk}: {e}",
                exc_info=True
            )
        
        # Verify password hash is still intact
        # The password should NOT be affected by identifier changes
        if instance.password:
            # Just log that password exists - don't modify it
            logger.debug(
                f"User {instance.pk}: Password hash verified intact after identifier change"
            )
    
    # Clear stored original values
    if instance.pk in _user_original_values:
        del _user_original_values[instance.pk]

