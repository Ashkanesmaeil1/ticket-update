import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import os
from django.conf import settings
from .models import Notification, User, EmailConfig, Department, TicketTask
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
import jdatetime
import zoneinfo
from django.db import models

def get_status_display_persian(status):
    """Convert status to Persian display text"""
    status_map = {
        'open': 'باز',
        'in_progress': 'در حال انجام',
        'waiting_for_user': 'در انتظار کاربر',
        'resolved': 'انجام شده',
        'closed': 'بسته',
    }
    return status_map.get(status, status)

def get_status_color(status):
    """Get consistent color for ticket status"""
    status_colors = {
        'open': '#ffc107',  # bg-warning (yellow)
        'in_progress': '#0d6efd',  # bg-primary (blue)
        'waiting_for_user': '#0dcaf0',  # bg-info (light blue)
        'resolved': '#198754',  # bg-success (green)
        'closed': '#6c757d',  # bg-secondary (gray)
    }
    return status_colors.get(status, '#6c757d')  # default to gray

def get_priority_color(priority):
    """Get consistent color for ticket priority"""
    priority_colors = {
        'low': '#28a745',  # bg-success (green)
        'medium': '#17a2b8',  # bg-info (blue)
        'high': '#ffc107',  # bg-warning (yellow)
        'urgent': '#dc3545',  # bg-danger (red)
    }
    return priority_colors.get(priority, '#6c757d')  # default to gray

def get_priority_display_persian(priority):
    """Convert priority to Persian display text"""
    priority_map = {
        'low': 'کم',
        'medium': 'متوسط',
        'high': 'زیاد',
        'urgent': 'فوری',
    }
    return priority_map.get(priority, priority)

def get_category_display_persian(category):
    """Convert category to Persian display text"""
    category_map = {
        'hardware': 'سخت‌افزار',
        'software': 'نرم‌افزار',
        'network': 'شبکه',
        'access': 'دسترسی شبکه',
        'other': 'سایر',
    }
    return category_map.get(category, category)

def get_user_role_display(user):
    """
    Get comprehensive role display for a user, including department name for employees and team leaders.
    
    Args:
        user: User object
        
    Returns:
        str: Role display text in Persian with department info
    """
    # For employees with specific department roles, show the department role as primary
    if user.role == 'employee' and user.department_role != 'employee':
        role_display = user.get_department_role_display()
        if user.department:
            role_display += f" ({user.department})"
        return role_display
    elif user.role == 'employee':
        role_display = user.get_role_display()
        if user.department:
            role_display += f" ({user.department})"
        return role_display
    else:
        return user.get_role_display()

def get_it_manager_ticket_ordering():
    """
    Get ordering for IT Manager tickets based on priority status.
    Order: Not assigned (open) -> Open -> Waiting for user -> In progress -> Closed -> Done (resolved)
    
    Returns:
        list: Ordering expressions for Django ORM
    """
    from django.db.models import Case, When, IntegerField, Value
    
    return [
        Case(
            When(status='open', assigned_to__isnull=True, then=Value(1)),
            When(status='open', then=Value(2)),
            When(status='waiting_for_user', then=Value(3)),
            When(status='in_progress', then=Value(4)),
            When(status='closed', then=Value(5)),
            When(status='resolved', then=Value(6)),
            default=Value(7),
            output_field=IntegerField(),
        ),
        '-created_at'  # Secondary ordering by creation date (newest first)
    ]

def get_iranian_date(datetime_obj):
    """Convert Gregorian date to Iranian date format"""
    try:
        # Convert to Tehran timezone if it's timezone-aware
        if timezone.is_aware(datetime_obj):
            tehran_tz = zoneinfo.ZoneInfo('Asia/Tehran')
            datetime_obj = datetime_obj.astimezone(tehran_tz)
        
        iranian_date = jdatetime.datetime.fromgregorian(datetime=datetime_obj)
        return iranian_date.strftime('%Y/%m/%d %H:%M')
    except:
        return datetime_obj.strftime('%Y/%m/%d %H:%M')

def get_iranian_time(datetime_obj):
    """Convert Gregorian time to Iranian time format"""
    try:
        # Convert to Tehran timezone if it's timezone-aware
        if timezone.is_aware(datetime_obj):
            tehran_tz = zoneinfo.ZoneInfo('Asia/Tehran')
            datetime_obj = datetime_obj.astimezone(tehran_tz)
        
        iranian_date = jdatetime.datetime.fromgregorian(datetime=datetime_obj)
        return iranian_date.strftime('%Y/%m/%d %H:%M')
    except:
        return datetime_obj.strftime('%Y/%m/%d %H:%M')

def get_iranian_datetime_full(datetime_obj):
    """Convert Gregorian datetime to full Iranian datetime format"""
    try:
        # Convert to Tehran timezone if it's timezone-aware
        if timezone.is_aware(datetime_obj):
            tehran_tz = zoneinfo.ZoneInfo('Asia/Tehran')
            datetime_obj = datetime_obj.astimezone(tehran_tz)
        
        iranian_date = jdatetime.datetime.fromgregorian(datetime=datetime_obj)
        return iranian_date.strftime('%Y/%m/%d %H:%M')
    except:
        return datetime_obj.strftime('%Y/%m/%d %H:%M')

def create_email_template(action_type, ticket, user, additional_info=None):
    """Create a beautiful email template with logo and proper formatting"""
    
    # Get Persian display values
    status_persian = get_status_display_persian(ticket.status)
    priority_persian = get_priority_display_persian(ticket.priority)
    category_persian = get_category_display_persian(ticket.category)
    
    # Action type mapping for email subjects (colloquial Persian)
    action_subject_map = {
        'create': 'تیکت جدید',
        'reply': 'پاسخ جدید',
        'status_change': 'تغییر وضعیت',
        'assignment': 'تخصیص تیکت',
        'update': 'ویرایش تیکت',
        'delete': 'حذف تیکت',
        'access_approved': 'تایید دسترسی شبکه',
        'access_rejected': 'رد دسترسی شبکه',
        'view': 'مشاهده تیکت',
    }
    
    # Action type mapping for email content
    action_map = {
        'create': 'ایجاد تیکت جدید',
        'reply': 'پاسخ به تیکت',
        'status_change': 'تغییر وضعیت تیکت',
        'assignment': 'تخصیص تیکت',
        'update': 'ویرایش تیکت',
        'delete': 'حذف تیکت',
        'access_approved': 'تایید درخواست دسترسی شبکه',
        'access_rejected': 'رد درخواست دسترسی شبکه',
        'view': 'مشاهده تیکت',
    }
    
    action_persian = action_map.get(action_type, action_type)
    action_subject_persian = action_subject_map.get(action_type, action_type)
    
    # Get Iranian date and time - ensure we're using the correct fields
    # For ticket creation date, always use ticket.created_at (should never change)
    ticket_creation_date = get_iranian_datetime_full(ticket.created_at)
    ticket_last_update = get_iranian_datetime_full(ticket.updated_at)
    
    # For access approved emails, use current time as approval time to ensure it's different
    approval_time_section = ""
    if action_type == 'access_approved':
        from django.utils import timezone
        current_time = timezone.now()
        approval_time = get_iranian_datetime_full(current_time)
        approval_time_section = f"""
                    <div class="info-row">
                        <span class="info-label">زمان تایید دسترسی:</span>
                        <span class="info-value">{approval_time}</span>
                    </div>"""
    
    # Determine the appropriate title for additional info section
    additional_info_title = "توضیحات تیکت"
    if action_type == 'reply':
        additional_info_title = "متن پاسخ"
    elif action_type == 'status_change':
        additional_info_title = "تغییرات وضعیت"
    elif action_type == 'assignment':
        additional_info_title = "اطلاعات تخصیص"
    elif action_type == 'update':
        additional_info_title = "تغییرات اعمال شده"
    elif action_type == 'delete':
        additional_info_title = "اطلاعات حذف"
    elif action_type == 'access_approved':
        additional_info_title = "جزئیات تایید دسترسی"
    elif action_type == 'view':
        additional_info_title = "اطلاعات مشاهده"
    
    # Base template with logo and styling
    html_template = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="fa">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{action_persian}</title>
        <style>
            body {{
                font-family: Tahoma, 'Segoe UI', Arial, sans-serif;
                margin: 0;
                padding: 0;
                background-color: #f5f5f5;
                direction: rtl;
                text-align: right;
                font-size: 16px;
                line-height: 1.7;
            }}
            .email-container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 10px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                overflow: hidden;
            }}
            .header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 30px 20px;
                text-align: center;
                color: white;
            }}
            .logo {{
                width: 80px;
                height: 80px;
                border-radius: 50%;
                margin-bottom: 15px;
                border: 3px solid rgba(255, 255, 255, 0.3);
            }}
            .header h1 {{
                margin: 0;
                font-size: 28px;
                font-weight: bold;
                margin-bottom: 5px;
            }}
            .header p {{
                margin: 0;
                font-size: 18px;
                opacity: 0.9;
            }}
            .content {{
                padding: 30px 20px;
                line-height: 1.8;
                direction: rtl;
                text-align: right;
            }}
            .info-section {{
                background-color: #f8f9fa;
                border-radius: 8px;
                padding: 20px;
                margin: 20px 0;
                border-right: 4px solid #667eea;
                direction: rtl;
                text-align: right;
            }}
            .info-row {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 15px;
                padding: 10px 0;
                border-bottom: 1px solid #e9ecef;
                direction: rtl;
            }}
            .info-row:last-child {{
                border-bottom: none;
                margin-bottom: 0;
            }}
            .info-label {{
                font-weight: bold;
                color: #495057;
                font-size: 17px;
                min-width: 120px;
                direction: rtl;
                text-align: right;
            }}
            .info-value {{
                color: #212529;
                font-size: 17px;
                text-align: right;
                direction: rtl;
            }}
            .ticket-title {{
                font-size: 22px;
                font-weight: bold;
                color: #2c3e50;
                margin-bottom: 20px;
                padding: 15px;
                background-color: #e3f2fd;
                border-radius: 6px;
                border-right: 4px solid #2196f3;
                direction: rtl;
                text-align: right;
            }}
            .user-info {{
                background-color: #e8f5e8;
                border-radius: 6px;
                padding: 15px;
                margin: 15px 0;
                border-right: 4px solid #4caf50;
                direction: rtl;
                text-align: right;
                font-size: 18px;
            }}
            .user-info strong {{ font-size: 18px; }}
            .user-info span {{ font-size: 18px; }}
            .footer {{
                background-color: #f8f9fa;
                padding: 20px;
                text-align: center;
                color: #6c757d;
                font-size: 15px;
                border-top: 1px solid #e9ecef;
            }}
            .badge {{
                display: inline-block;
                padding: 2px 6px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
                color: #212529;
                background-color: transparent;
                border: 1px solid #dee2e6;
                direction: rtl;
            }}
            .badge-status {{ font-size: 15px; }}
            .badge-priority {{ font-size: 15px; }}
            .badge-category {{ font-size: 15px; }}
            .additional-info {{
                background-color: #fff3cd;
                border: 1px solid #ffeaa7;
                border-radius: 6px;
                padding: 15px;
                margin: 15px 0;
                direction: rtl;
                text-align: right;
                font-size: 17px;
            }}
            .additional-info strong {{ font-size: 18px; }}
        </style>
    </head>
    <body>
        <div class="email-container">
            <div class="header">
                <img src="cid:logo" alt="لوگو" class="logo">
                <h1>{action_persian}</h1>
                <p>سیستم مدیریت تیکت</p>
            </div>
            
            <div class="content">
                <div class="ticket-title">📋 <span dir="auto">{ticket.title}</span></div>
                
                <div class="user-info">
                    <strong>👤 کاربر:</strong> <span dir="auto">{user.get_full_name() or user.username}</span>"""
    
    # Add department line only if user is not a manager
    if hasattr(user, 'department_role') and user.department_role != 'manager':
        html_template += f"""
                    <br>
                    <strong>🏢 بخش:</strong> <span dir=\"auto\">{user.department or 'نامشخص'}</span>"""
    
    html_template += f"""
                </div>
                
                <div class="info-section">
                    <div class="info-row">
                        <span class="info-label">وضعیت:</span>
                        <span class="info-value">
                            <span class="badge badge-status">{status_persian}</span>
                        </span>
                    </div>
                    
                    <div class="info-row">
                        <span class="info-label">اولویت:</span>
                        <span class="info-value">
                            <span class="badge badge-priority">{priority_persian}</span>
                        </span>
                    </div>
                    
                    <div class="info-row">
                        <span class="info-label">دسته‌بندی:</span>
                        <span class="info-value">
                            <span class="badge badge-category">{category_persian}</span>
                        </span>
                    </div>
                    
                    <div class="info-row">
                        <span class="info-label">شماره تیکت:</span>
                        <span class="info-value">#{ticket.id}</span>
                    </div>
                    
                    <div class="info-row">
                        <span class="info-label">تاریخ و زمان ایجاد اولیه:</span>
                        <span class="info-value">{ticket_creation_date}</span>
                    </div>{approval_time_section}
                    
                    <div class="info-row">
                        <span class="info-label">آخرین تغییرات:</span>
                        <span class="info-value">{ticket_last_update}</span>
                    </div>
                </div>
    """
    
    # Add additional info if provided
    if additional_info:
        html_template += f"""
                <div class="additional-info">
                    <strong>📝 {additional_info_title}:</strong><br>
                    <div dir=\"auto\" style=\"white-space: pre-wrap;\">{additional_info}</div>
                </div>
        """
    
    # Close the template
    html_template += """
            </div>
        </div>
    </body>
    </html>
    """
    
    return html_template

def create_notification(recipient, title, message, notification_type, category='system', ticket=None, user_actor=None):
    """Create a notification in the database"""
    # Self-action exclusion: Don't create notification if the actor is the same as the recipient
    # This prevents IT Manager from receiving notifications about their own actions
    if user_actor and recipient and user_actor.id == recipient.id:
        return None
    
    try:
        notification = Notification.objects.create(
            recipient=recipient,
            title=title,
            message=message,
            notification_type=notification_type,
            category=category,
            ticket=ticket,
            user_actor=user_actor
        )
        return notification
    except Exception as e:
        print(f"⚠️ Failed to create notification: {e}")
        return None

def notify_team_leader_network_access(ticket, user):
    """
    Send notification to team leader when a Network Access ticket is created by department staff.
    
    Args:
        ticket: Ticket object (must be Network Access category)
        user: User object who created the ticket
    """
    print(f"🔍 notify_team_leader_network_access called for ticket #{ticket.id} by {user.get_full_name()}")
    print(f"🔍 User department: {user.department}, User department_role: {user.department_role}")
    print(f"🔍 User department type: {type(user.department)}")
    if user.department:
        print(f"🔍 User department name: {user.department.name}")
    
    try:
        # Find team leader in the same department
        team_leader = User.objects.filter(
            role='employee',
            department_role='senior',
            department=user.department
        ).first()
        
        print(f"🔍 Found team leader: {team_leader.get_full_name() if team_leader else 'None'}")
        
        if team_leader:
            create_notification(
                recipient=team_leader,
                title=f"درخواست دسترسی شبکه جدید: {ticket.title}",
                message=f"کارمند: {user.get_full_name()}\nبخش: {user.get_department_display()}\nاولویت: {ticket.get_priority_display()}\nتوضیحات: {ticket.description[:200]}{'...' if len(ticket.description) > 200 else ''}",
                notification_type='access_pending_approval',
                category='team_leader_access',
                ticket=ticket,
                user_actor=user
            )
            print(f"✅ Team leader notification created for {team_leader.get_full_name()} about Network Access ticket #{ticket.id}")
        else:
            print(f"⚠️ No team leader found for department: {user.department}")
            # Debug: Check what departments exist
            all_departments = Department.objects.all()
            print(f"🔍 All departments: {[dept.name for dept in all_departments]}")
            # Debug: Check what users exist in this department
            dept_users = User.objects.filter(department=user.department)
            print(f"🔍 Users in department {user.department}: {[f'{u.get_full_name()} ({u.department_role})' for u in dept_users]}")
    except Exception as e:
        print(f"⚠️ Failed to create team leader notification: {e}")
        import traceback
        traceback.print_exc()

def notify_team_leader_access_email(action_type, ticket, user, additional_info=None):
    """
    Send email to the team leader (senior employee) in the creator's department
    for Network Access tickets that are pending approval.
    Reuses the employee email template, targeting the team leader email.
    """
    try:
        # Find team leader in the same department as ticket creator
        creator = ticket.created_by
        if not creator or not creator.department:
            print("⚠️ Cannot find creator or department to route team leader email")
            return
        team_leader = User.objects.filter(
            role='employee',
            department_role='senior',
            department=creator.department
        ).first()
        if not team_leader or not team_leader.email:
            print("⚠️ No team leader with email found for department")
            return
        # Send using the same beautiful template
        notify_employee(action_type, ticket, user, additional_info, employee_email=team_leader.email)
    except Exception as e:
        print(f"⚠️ Failed to email team leader for access ticket: {e}")

def notify_department_supervisor(ticket, target_department, user):
    """
    Notify the supervisor (senior) of the target department when a ticket is created for that department.
    This is used when tickets are sent to non-IT departments.
    
    Args:
        ticket: Ticket object
        target_department: Department object that the ticket is sent to
        user: User object who created the ticket
    """
    try:
        # Find supervisor (senior) in the target department
        supervisor = User.objects.filter(
            role='employee',
            department_role='senior',
            department=target_department
        ).first()
        
        if supervisor:
            # Create in-app notification
            create_notification(
                recipient=supervisor,
                title=f"تیکت جدید برای بخش شما: {ticket.title}",
                message=f"کاربر: {user.get_full_name()}\nبخش: {target_department.name}\nاولویت: {ticket.get_priority_display()}\nتوضیحات: {ticket.description[:200]}{'...' if len(ticket.description) > 200 else ''}",
                notification_type='ticket_created',
                category='tickets',
                ticket=ticket,
                user_actor=user
            )
            
            # Send email if supervisor has email
            if supervisor.email:
                notify_employee('create', ticket, user, ticket.description, employee_email=supervisor.email)
            
            print(f"✅ Department supervisor notification created for {supervisor.get_full_name()} about ticket #{ticket.id}")
        else:
            print(f"⚠️ No supervisor found for department: {target_department.name}")
    except Exception as e:
        print(f"⚠️ Failed to notify department supervisor: {e}")
        import traceback
        traceback.print_exc()

def notify_it_manager(action_type, ticket, user, additional_info=None):
    """
    Send a beautiful email notification to the IT manager.
    
    Args:
        action_type (str): Type of action (create, reply, status_change, assignment, update, delete)
        ticket: Ticket object
        user: User object who performed the action
        additional_info (str): Additional information to include in the email
    """
    try:
        # Create email content
        html_content = create_email_template(action_type, ticket, user, additional_info)
        
        # Get Persian subject text
        action_subject_map = {
            'create': 'تیکت جدید',
            'reply': 'پاسخ جدید',
            'status_change': 'تغییر وضعیت',
            'assignment': 'تخصیص تیکت',
            'update': 'ویرایش تیکت',
            'delete': 'حذف تیکت',
            'access_approved': 'تایید دسترسی شبکه',
            'access_rejected': 'رد دسترسی شبکه',
        }
        subject_text = action_subject_map.get(action_type, action_type)
        
        # Create message with Persian subject
        msg = MIMEMultipart('related')
        # Add RTL marker to ensure proper text direction in subject
        msg["Subject"] = f"\u202B{subject_text}\u202C"
        # Determine recipient (IT manager mailbox from config, fallback to first IT manager's email)
        cfg = EmailConfig.get_active()
        recipient_email = None
        if cfg and cfg.username:
            recipient_email = cfg.username
        else:
            manager = User.objects.filter(role='it_manager').exclude(email='').first()
            if manager and manager.email:
                recipient_email = manager.email
        if recipient_email:
            msg["To"] = recipient_email
        
        # i should change it to it itss@pargasiran.com
        
        # Create HTML part
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)
        
        # Try to attach logo
        try:
            logo_path = os.path.join(settings.STATIC_ROOT, 'admin', 'img', 'white-pargsStar.webp')
            if not os.path.exists(logo_path) and getattr(settings, 'STATICFILES_DIRS', None):
                logo_path = os.path.join(settings.STATICFILES_DIRS[0], 'admin', 'img', 'white-pargsStar.webp')
            
            if os.path.exists(logo_path):
                with open(logo_path, 'rb') as f:
                    logo_img = MIMEImage(f.read())
                    logo_img.add_header('Content-ID', '<logo>')
                    logo_img.add_header('Content-Disposition', 'inline', filename='logo.webp')
                    msg.attach(logo_img)
        except Exception as e:
            print(f"⚠️ Could not attach logo: {e}")
        
        # Resolve SMTP config
        smtp_host = cfg.host or getattr(settings, 'EMAIL_HOST', None)
        smtp_port = cfg.port or getattr(settings, 'EMAIL_PORT', 587)
        use_tls = cfg.use_tls if cfg is not None else getattr(settings, 'EMAIL_USE_TLS', True)
        use_ssl = cfg.use_ssl if cfg is not None else getattr(settings, 'EMAIL_USE_SSL', False)
        smtp_user = cfg.username or getattr(settings, 'EMAIL_HOST_USER', None)
        smtp_pass = cfg.password or getattr(settings, 'EMAIL_HOST_PASSWORD', None)

        # Optional from headers
        if cfg and (cfg.username or cfg.from_name):
            from_header = cfg.from_name + f" <{cfg.username}>" if cfg.from_name and cfg.username else (cfg.username or '')
            if from_header:
                msg["From"] = from_header

        # Guard against missing host
        if not smtp_host:
            print("❌ SMTP host is not configured. Set it in Email Settings.")
            return
        if not recipient_email:
            print("❌ No IT manager recipient email resolved. Set username in Email Settings or IT manager email.")
            return

        # Send email via configured backend
        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port)
        try:
            if use_tls and not use_ssl:
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        finally:
            server.quit()
        print("✅ Email sent successfully!")
        
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

    # Create in-app notification for IT manager (admin-only phase)
    try:
        it_managers = User.objects.filter(role='it_manager')
        for manager in it_managers:
            if action_type == 'create':
                # Determine notification category based on ticket category
                notification_category = 'access' if ticket.category == 'access' else 'tickets'
                create_notification(
                    recipient=manager,
                    title=f"تیکت جدید: {ticket.title}",
                    message=f"کاربر: {user.get_full_name()}\nاولویت: {ticket.get_priority_display()}\nدسته: {ticket.get_category_display()}",
                    notification_type='ticket_created',
                    category=notification_category,
                    ticket=ticket,
                    user_actor=user
                )
            elif action_type == 'update' and getattr(ticket, 'status', None) == 'resolved':
                create_notification(
                    recipient=manager,
                    title=_('تیکت انجام شده'),
                    message=f"تیکت #{ticket.id} با عنوان '{ticket.title}' به وضعیت انجام شده تغییر یافت.",
                    notification_type='status_done',
                    category='tickets',
                    ticket=ticket,
                    user_actor=user
                )
            elif action_type == 'reply':
                create_notification(
                    recipient=manager,
                    title=f"پاسخ جدید: {ticket.title}",
                    message=f"پاسخ جدید برای تیکت #{ticket.id} توسط {user.get_full_name()}",
                    notification_type='ticket_urgent',
                    category='tickets',
                    ticket=ticket,
                    user_actor=user
                )
            elif action_type == 'status_change':
                create_notification(
                    recipient=manager,
                    title=f"تغییر وضعیت: {ticket.title}",
                    message=f"وضعیت تیکت #{ticket.id} تغییر یافت توسط {user.get_full_name()}",
                    notification_type='ticket_urgent',
                    category='tickets',
                    ticket=ticket,
                    user_actor=user
                )
            elif action_type == 'assignment':
                create_notification(
                    recipient=manager,
                    title=f"اختصاص تیکت: {ticket.title}",
                    message=f"تیکت #{ticket.id} به {ticket.assigned_to.get_full_name() if ticket.assigned_to else 'کاربر نامشخص'} تخصیص داده شد",
                    notification_type='ticket_urgent',
                    category='tickets',
                    ticket=ticket,
                    user_actor=user
                )
    except Exception as e:
        print(f"⚠️ Failed to create notification: {e}")

def notify_employee(action_type, ticket, user, additional_info=None, employee_email=None):
    """
    Send a beautiful email notification to an employee about their ticket.
    
    Args:
        action_type (str): Type of action (create, reply, status_change, assignment, update, delete)
        ticket: Ticket object (can be None for delete action)
        user: User object who performed the action
        additional_info (str): Additional information to include in the email
        employee_email (str): Employee's email address (if None, will use ticket creator's email)
    """
    try:
        # Determine the recipient email
        if action_type == 'delete' and ticket is None:
            # For deleted tickets, we must have employee_email
            recipient_email = employee_email
        else:
            recipient_email = employee_email or getattr(ticket.created_by, 'email', None)
        
        if not recipient_email:
            print("❌ No email address found for employee notification")
            return
        
        # Create email content - handle deleted tickets specially
        if action_type == 'delete' and ticket is None:
            html_content = create_deletion_email_template(user, additional_info)
        else:
            html_content = create_email_template(action_type, ticket, user, additional_info)
        
        # Get Persian subject text
        action_subject_map = {
            'create': 'تیکت جدید',
            'reply': 'پاسخ جدید',
            'status_change': 'تغییر وضعیت',
            'assignment': 'تخصیص تیکت',
            'update': 'ویرایش تیکت',
            'delete': 'حذف تیکت',
            'view': 'مشاهده تیکت',
        }
        subject_text = action_subject_map.get(action_type, action_type)
        
        # Create message with Persian subject (no ticket title)
        msg = MIMEMultipart('related')
        # Add RTL marker to ensure proper text direction in subject
        msg["Subject"] = f"\u202B{subject_text}\u202C"
        # From header from config if available
        cfg = EmailConfig.get_active()
        if cfg and (cfg.username or cfg.from_name):
            msg["From"] = cfg.from_name + f" <{cfg.username}>" if cfg.from_name and cfg.username else (cfg.username or '')
        msg["To"] = recipient_email
        
        # Create HTML part
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)
        
        # Try to attach logo
        try:
            logo_path = os.path.join(settings.STATIC_ROOT, 'admin', 'img', 'white-pargsStar.webp')
            if not os.path.exists(logo_path) and getattr(settings, 'STATICFILES_DIRS', None):
                logo_path = os.path.join(settings.STATICFILES_DIRS[0], 'admin', 'img', 'white-pargsStar.webp')
            
            if os.path.exists(logo_path):
                with open(logo_path, 'rb') as f:
                    logo_img = MIMEImage(f.read())
                    logo_img.add_header('Content-ID', '<logo>')
                    logo_img.add_header('Content-Disposition', 'inline', filename='logo.webp')
                    msg.attach(logo_img)
        except Exception as e:
            print(f"⚠️ Could not attach logo: {e}")
        
        # Resolve SMTP config
        smtp_host = cfg.host or getattr(settings, 'EMAIL_HOST', None)
        smtp_port = cfg.port or getattr(settings, 'EMAIL_PORT', 587)
        use_tls = cfg.use_tls if cfg is not None else getattr(settings, 'EMAIL_USE_TLS', True)
        use_ssl = cfg.use_ssl if cfg is not None else getattr(settings, 'EMAIL_USE_SSL', False)
        smtp_user = cfg.username or getattr(settings, 'EMAIL_HOST_USER', None)
        smtp_pass = cfg.password or getattr(settings, 'EMAIL_HOST_PASSWORD', None)

        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port)
        try:
            if use_tls and not use_ssl:
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        finally:
            server.quit()
        print(f"✅ Employee email sent successfully to {recipient_email}!")
        
    except Exception as e:
        print(f"❌ Failed to send employee email: {e}")


def create_task_deadline_reminder_html(task, hours_remaining):
    """Create HTML content for task deadline reminder email (8h or 2h remaining)."""
    deadline_str = get_iranian_datetime_full(task.deadline) if task.deadline else ''
    hours_label = '۸ ساعت' if hours_remaining == 8 else '۲ ساعت'
    title = task.title or _('تسک')
    priority_persian = get_priority_display_persian(task.priority) if hasattr(task, 'priority') else ''
    status_persian = get_status_display_persian(task.status) if hasattr(task, 'status') else ''
    html = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="fa">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="Content-Language" content="fa">
        <title>یادآور مهلت تسک</title>
        <style>
            body {{ font-family: Tahoma, 'Segoe UI', Arial, sans-serif; margin: 0; padding: 0; background-color: #f5f5f5; direction: rtl; text-align: right; font-size: 16px; line-height: 1.7; }}
            .email-container {{ max-width: 600px; margin: 0 auto; background-color: #fff; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); overflow: hidden; direction: rtl; text-align: right; }}
            .header {{ background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); padding: 25px 20px; text-align: right; color: white; direction: rtl; }}
            .header h1 {{ margin: 0; font-size: 22px; text-align: right; }}
            .header p {{ margin: 0.5em 0 0 0; text-align: right; }}
            .content {{ padding: 25px 20px; direction: rtl; text-align: right; }}
            .content p {{ text-align: right; margin: 0 0 1em 0; }}
            .info-section {{ background-color: #fffbeb; border-radius: 8px; padding: 16px; margin: 16px 0; border-right: 4px solid #f59e0b; direction: rtl; text-align: right; }}
            .info-row {{ margin: 8px 0; text-align: right; direction: rtl; }}
            .info-label {{ font-weight: bold; color: #92400e; }}
            .deadline-highlight {{ color: #b45309; font-weight: bold; font-size: 18px; }}
        </style>
    </head>
    <body style="direction: rtl; text-align: right;">
        <div class="email-container" style="direction: rtl; text-align: right;">
            <div class="header" style="text-align: right; direction: rtl;">
                <h1 style="text-align: right;">⏰ یادآور مهلت تسک تیکت</h1>
                <p style="text-align: right;">حدود {hours_label} به مهلت انجام تسک باقی مانده است.</p>
            </div>
            <div class="content" style="direction: rtl; text-align: right;">
                <p style="text-align: right;">سلام،</p>
                <p style="text-align: right;">این ایمیل یادآوری است برای تسک تیکت زیر که مهلت انجام آن به زودی به پایان می‌رسد.</p>
                <div class="info-section" style="direction: rtl; text-align: right;">
                    <div class="info-row" style="text-align: right;"><span class="info-label">عنوان تسک:</span> {title}</div>
                    <div class="info-row" style="text-align: right;"><span class="info-label">شماره تسک:</span> #{task.id}</div>
                    <div class="info-row" style="text-align: right;"><span class="info-label">اولویت:</span> {priority_persian}</div>
                    <div class="info-row" style="text-align: right;"><span class="info-label">وضعیت:</span> {status_persian}</div>
                    <div class="info-row" style="text-align: right;"><span class="info-label">مهلت انجام:</span> <span class="deadline-highlight">{deadline_str}</span></div>
                </div>
                <p style="text-align: right;">لطفاً در صورت نیاز اقدام به تکمیل یا درخواست تمدید مهلت کنید.</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html


def send_task_deadline_reminder_email(task, hours_remaining):
    """
    Send deadline reminder email to the user assigned to the task (8h or 2h remaining).
    Uses the same SMTP config as other system emails.
    """
    if not task or not task.assigned_to:
        return False
    recipient_email = getattr(task.assigned_to, 'email', None)
    if not recipient_email or not recipient_email.strip():
        return False
    try:
        html_content = create_task_deadline_reminder_html(task, hours_remaining)
        if hours_remaining == 8:
            subject_full = '\u202Bیادآور مهلت: ۸ ساعت تا پایان مهلت تسک\u202C'
        else:
            subject_full = '\u202Bیادآور مهلت: ۲ ساعت تا پایان مهلت تسک\u202C'
        msg = MIMEMultipart('related')
        msg['Subject'] = subject_full
        cfg = EmailConfig.get_active()
        if cfg and (cfg.username or cfg.from_name):
            msg['From'] = (cfg.from_name + f' <{cfg.username}>') if (cfg.from_name and cfg.username) else (cfg.username or '')
        msg['To'] = recipient_email
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)
        smtp_host = cfg.host or getattr(settings, 'EMAIL_HOST', None)
        smtp_port = cfg.port or getattr(settings, 'EMAIL_PORT', 587)
        use_tls = cfg.use_tls if cfg is not None else getattr(settings, 'EMAIL_USE_TLS', True)
        use_ssl = cfg.use_ssl if cfg is not None else getattr(settings, 'EMAIL_USE_SSL', False)
        smtp_user = cfg.username or getattr(settings, 'EMAIL_HOST_USER', None)
        smtp_pass = cfg.password or getattr(settings, 'EMAIL_HOST_PASSWORD', None)
        if not smtp_host:
            return False
        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port)
        try:
            if use_tls and not use_ssl:
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        finally:
            server.quit()
        import logging
        logging.getLogger(__name__).info(
            'Task deadline reminder email sent: task_id=%s, hours=%s, to=%s',
            getattr(task, 'id', None), hours_remaining, recipient_email
        )
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception('Failed to send task deadline reminder email: %s', e)
        return False


# Deadline reminder windows (hours): 8h when 7.5 < remaining <= 8.5, 2h when 1.5 < remaining <= 2.5
TASK_DEADLINE_WINDOW_8H_MIN = 7.5
TASK_DEADLINE_WINDOW_8H_MAX = 8.5
TASK_DEADLINE_WINDOW_2H_MIN = 1.5
TASK_DEADLINE_WINDOW_2H_MAX = 2.5


def run_task_deadline_reminders(dry_run=False):
    """
    Check all open tasks with deadline and send 8h/2h reminder emails as needed.
    Called automatically by the in-app scheduler and by the management command.
    Returns (sent_8h_count, sent_2h_count).
    """
    import logging
    logger = logging.getLogger(__name__)
    now = timezone.now()
    tasks = TicketTask.objects.filter(
        deadline__gt=now,
        deadline__isnull=False,
        status__in=['open', 'in_progress', 'waiting_for_user'],
        assigned_to__isnull=False,
    ).exclude(
        assigned_to__email='',
    ).exclude(
        assigned_to__email__isnull=True,
    ).select_related('assigned_to')

    sent_8h = 0
    sent_2h = 0

    for task in tasks:
        remaining_seconds = (task.deadline - now).total_seconds()
        remaining_hours = remaining_seconds / 3600.0

        if remaining_hours <= TASK_DEADLINE_WINDOW_2H_MIN:
            continue

        if not task.deadline_reminder_8h_sent and (TASK_DEADLINE_WINDOW_8H_MIN < remaining_hours <= TASK_DEADLINE_WINDOW_8H_MAX):
            if dry_run:
                sent_8h += 1
            else:
                if send_task_deadline_reminder_email(task, 8):
                    task.deadline_reminder_8h_sent = True
                    task.save(update_fields=['deadline_reminder_8h_sent'])
                    sent_8h += 1
                    logger.info('Sent 8h deadline reminder for task #%s to %s', task.id, getattr(task.assigned_to, 'email', ''))

        elif not task.deadline_reminder_2h_sent and (TASK_DEADLINE_WINDOW_2H_MIN < remaining_hours <= TASK_DEADLINE_WINDOW_2H_MAX):
            if dry_run:
                sent_2h += 1
            else:
                if send_task_deadline_reminder_email(task, 2):
                    task.deadline_reminder_2h_sent = True
                    task.save(update_fields=['deadline_reminder_2h_sent'])
                    sent_2h += 1
                    logger.info('Sent 2h deadline reminder for task #%s to %s', task.id, getattr(task.assigned_to, 'email', ''))

    return sent_8h, sent_2h


def create_task_assigned_email_html(task, assigned_by_user):
    """Create HTML content for 'task assigned to you' email."""
    deadline_str = get_iranian_datetime_full(task.deadline) if task.deadline else _('تعیین نشده')
    title = task.title or _('تسک')
    priority_persian = get_priority_display_persian(task.priority) if hasattr(task, 'priority') else ''
    status_persian = get_status_display_persian(task.status) if hasattr(task, 'status') else ''
    assigner_name = (assigned_by_user.get_full_name() or assigned_by_user.username) if assigned_by_user else _('سیستم')
    html = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="fa">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>تسک جدید به شما اختصاص داده شد</title>
        <style>
            body {{ font-family: Tahoma, 'Segoe UI', Arial, sans-serif; margin: 0; padding: 0; background-color: #f5f5f5; direction: rtl; text-align: right; font-size: 16px; line-height: 1.7; }}
            .email-container {{ max-width: 600px; margin: 0 auto; background-color: #fff; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); padding: 25px 20px; text-align: center; color: white; }}
            .header h1 {{ margin: 0; font-size: 22px; }}
            .content {{ padding: 25px 20px; }}
            .info-section {{ background-color: #eff6ff; border-radius: 8px; padding: 16px; margin: 16px 0; border-right: 4px solid #2563eb; }}
            .info-row {{ margin: 8px 0; }}
            .info-label {{ font-weight: bold; color: #1e40af; }}
        </style>
    </head>
    <body>
        <div class="email-container">
            <div class="header">
                <h1>تسک جدید به شما اختصاص داده شد</h1>
                <p>یک تسک تیکت برای شما تعیین شده است.</p>
            </div>
            <div class="content">
                <p>سلام،</p>
                <p>تسک زیر توسط «{assigner_name}» به شما اختصاص داده شده است. لطفاً در اسرع وقت آن را بررسی کنید.</p>
                <div class="info-section">
                    <div class="info-row"><span class="info-label">عنوان تسک:</span> {title}</div>
                    <div class="info-row"><span class="info-label">شماره تسک:</span> #{task.id}</div>
                    <div class="info-row"><span class="info-label">اولویت:</span> {priority_persian}</div>
                    <div class="info-row"><span class="info-label">وضعیت:</span> {status_persian}</div>
                    <div class="info-row"><span class="info-label">مهلت انجام:</span> {deadline_str}</div>
                </div>
                <p>برای مشاهده جزئیات و اقدام، به پنل تسک‌های تیکت مراجعه کنید.</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html


def send_task_assigned_email(task, assigned_by_user):
    """
    Send email to the user when a task is assigned to them (create or reassign).
    Uses the same SMTP config as other system emails.
    """
    if not task or not task.assigned_to:
        return False
    recipient_email = getattr(task.assigned_to, 'email', None)
    if not recipient_email or not recipient_email.strip():
        return False
    try:
        html_content = create_task_assigned_email_html(task, assigned_by_user)
        subject_full = '\u202Bتسک جدید به شما اختصاص داده شد\u202C'
        msg = MIMEMultipart('related')
        msg['Subject'] = subject_full
        cfg = EmailConfig.get_active()
        if cfg and (cfg.username or cfg.from_name):
            msg['From'] = (cfg.from_name + f' <{cfg.username}>') if (cfg.from_name and cfg.username) else (cfg.username or '')
        msg['To'] = recipient_email
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)
        smtp_host = cfg.host or getattr(settings, 'EMAIL_HOST', None)
        smtp_port = cfg.port or getattr(settings, 'EMAIL_PORT', 587)
        use_tls = cfg.use_tls if cfg is not None else getattr(settings, 'EMAIL_USE_TLS', True)
        use_ssl = cfg.use_ssl if cfg is not None else getattr(settings, 'EMAIL_USE_SSL', False)
        smtp_user = cfg.username or getattr(settings, 'EMAIL_HOST_USER', None)
        smtp_pass = cfg.password or getattr(settings, 'EMAIL_HOST_PASSWORD', None)
        if not smtp_host:
            return False
        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port)
        try:
            if use_tls and not use_ssl:
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        finally:
            server.quit()
        import logging
        logging.getLogger(__name__).info(
            'Task assigned email sent: task_id=%s, to=%s',
            getattr(task, 'id', None), recipient_email
        )
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception('Failed to send task assigned email: %s', e)
        return False


def create_deletion_email_template(user, additional_info=None):
    """Create a special email template for deleted tickets"""
    
    from django.utils import timezone
    
    # Base template with logo and styling
    html_template = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="fa">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>حذف تیکت</title>
        <style>
            body {{
                font-family: Tahoma, 'Segoe UI', Arial, sans-serif;
                margin: 0;
                padding: 0;
                background-color: #f5f5f5;
                direction: rtl;
                text-align: right;
                font-size: 16px;
                line-height: 1.7;
            }}
            .email-container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 10px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                overflow: hidden;
            }}
            .header {{
                background: linear-gradient(135deg, #dc3545 0%, #c82333 100%);
                padding: 30px 20px;
                text-align: center;
                color: white;
            }}
            .logo {{
                width: 80px;
                height: 80px;
                border-radius: 50%;
                margin-bottom: 15px;
                border: 3px solid rgba(255, 255, 255, 0.3);
            }}
            .header h1 {{
                margin: 0;
                font-size: 28px;
                font-weight: bold;
                margin-bottom: 5px;
            }}
            .header p {{
                margin: 0;
                font-size: 18px;
                opacity: 0.9;
            }}
            .content {{
                padding: 30px 20px;
                line-height: 1.8;
                direction: rtl;
                text-align: right;
            }}
            .info-section {{
                background-color: #f8d7da;
                border-radius: 8px;
                padding: 20px;
                margin: 20px 0;
                border-right: 4px solid #dc3545;
                direction: rtl;
                text-align: right;
            }}
            .info-row {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 15px;
                padding: 10px 0;
                border-bottom: 1px solid #f5c6cb;
                direction: rtl;
            }}
            .info-row:last-child {{
                border-bottom: none;
                margin-bottom: 0;
            }}
            .info-label {{
                font-weight: bold;
                color: #721c24;
                font-size: 17px;
                min-width: 120px;
                direction: rtl;
                text-align: right;
            }}
            .info-value {{
                color: #721c24;
                font-size: 17px;
                text-align: right;
                direction: rtl;
            }}
            .user-info {{
                background-color: #e8f5e8;
                border-radius: 6px;
                padding: 15px;
                margin: 15px 0;
                border-right: 4px solid #4caf50;
                direction: rtl;
                text-align: right;
                font-size: 18px;
            }}
            .user-info strong {{ font-size: 18px; }}
            .user-info span {{ font-size: 18px; }}
            .additional-info {{
                background-color: #fff3cd;
                border: 1px solid #ffeaa7;
                border-radius: 6px;
                padding: 15px;
                margin: 15px 0;
                direction: rtl;
                text-align: right;
                font-size: 17px;
            }}
            .additional-info strong {{ font-size: 18px; }}
        </style>
    </head>
    <body>
        <div class="email-container">
            <div class="header">
                <img src="cid:logo" alt="لوگو" class="logo">
                <h1>حذف تیکت</h1>
                <p>سیستم مدیریت تیکت</p>
            </div>
            
            <div class="content">
                <div class="user-info">
                    <strong>👤 کاربر:</strong> <span dir="auto">{user.get_full_name() or user.username}</span>"""
    
    # Add department line only if user is not a manager
    if hasattr(user, 'department_role') and user.department_role != 'manager':
        html_template += f"""
                    <br>
                    <strong>🏢 بخش:</strong> <span dir=\"auto\">{user.department or 'نامشخص'}</span>"""
    
    html_template += f"""
                </div>
                
                <div class="info-section">
                    <div class="info-row">
                        <span class="info-label">نوع عملیات:</span>
                        <span class="info-value">حذف تیکت</span>
                    </div>
                    
                    <div class="info-row">
                        <span class="info-label">تاریخ و زمان:</span>
                        <span class="info-value">{get_iranian_datetime_full(timezone.now())}</span>
                    </div>
                </div>
    """
    
    # Add additional info if provided
    if additional_info:
        html_template += f"""
                <div class="additional-info">
                    <strong>📝 جزئیات حذف:</strong><br>
                    <div dir=\"auto\" style=\"white-space: pre-wrap;\">{additional_info}</div>
                </div>
        """
    
    # Close the template
    html_template += """
            </div>
        </div>
    </body>
    </html>
    """
    
    return html_template

def notify_employee_ticket_created(ticket):
    """
    Send notification to employee when their ticket is created
    """
    if ticket.created_by.email:
        notify_employee('create', ticket, ticket.created_by, ticket.description)

def notify_employee_ticket_replied(ticket, reply):
    """
    Send notification to employee when someone replies to their ticket
    """
    if ticket.created_by.email:
        # For private replies, don't send content in email
        content = reply.content if not reply.is_private else "[پاسخ محرمانه]"
        notify_employee('reply', ticket, reply.author, content)

def notify_employee_ticket_status_changed(ticket, user):
    """
    Send notification to employee when their ticket status changes
    """
    if ticket.created_by.email:
        status_persian = get_status_display_persian(ticket.status)
        additional_info = f"وضعیت تیکت شما به «{status_persian}» تغییر یافت."
        notify_employee('status_change', ticket, user, additional_info)

def notify_employee_ticket_assigned(ticket, user):
    """
    Send notification to employee when their ticket is assigned to someone
    """
    if ticket.created_by.email and ticket.assigned_to:
        assigned_to_name = ticket.assigned_to.get_full_name() or ticket.assigned_to.username
        additional_info = f"تیکت شما به «{assigned_to_name}» تخصیص داده شد."
        notify_employee('assignment', ticket, user, additional_info)

def notify_employee_account_created(user, created_by):
    """
    Send notification to new employee when their account is created
    """
    if user.email:
        # Create a dummy ticket for the email template
        from .models import Ticket
        dummy_ticket = Ticket.objects.first()
        if dummy_ticket:
            additional_info = f"""
            حساب کاربری شما در سیستم مدیریت تیکت ایجاد شد.
            
            اطلاعات حساب:
            نام: {user.first_name} {user.last_name}
            کد پرسنلی: {user.employee_code}
            بخش: {user.department or 'نامشخص'}
            نقش: {user.get_role_display()}
            
            شما می‌توانید از طریق کد ملی و کد پرسنلی خود وارد سیستم شوید.
            """
            notify_employee('create', dummy_ticket, created_by, additional_info, user.email)

def create_it_manager_login_notification(user, ip_address):
    """
    Create a notification when an IT manager logs in, including IP address information.
    
    Args:
        user: User object (IT manager)
        ip_address (str): IP address of the system that logged in
    """
    try:
        # Get all IT managers to notify them about the login
        it_managers = User.objects.filter(role='it_manager')
        for manager in it_managers:
            create_notification(
                recipient=manager,
                title=f"ورود مدیر IT: {user.get_full_name()}",
                message=f"مدیر IT وارد سیستم شد.\nزمان: {get_iranian_datetime_full(timezone.now())}\nآدرس آی‌پی: {ip_address}",
                notification_type='login',
                category='system',
                user_actor=user
            )
        print(f"✅ IT Manager login notification created for {user.get_full_name()} from IP: {ip_address}")
    except Exception as e:
        print(f"⚠️ Failed to create IT manager login notification: {e}")

def notify_it_manager_user_management(action_type, user, actor):
    """
    Send a beautiful email notification to the IT manager about user management operations.
    
    Args:
        action_type (str): Type of action (create, update, delete)
        user: User object being managed
        actor: User object who performed the action
    """
    try:
        # Create email content
        html_content = create_user_management_email_template(action_type, user, actor)
        
        # Get Persian subject text
        action_subject_map = {
            'create': 'ایجاد کاربر جدید',
            'update': 'ویرایش اطلاعات کاربر',
            'delete': 'حذف کاربر',
        }
        subject_text = action_subject_map.get(action_type, action_type)
        
        # Create message with Persian subject
        msg = MIMEMultipart('related')
        # Add RTL marker to ensure proper text direction in subject
        msg["Subject"] = f"\u202B{subject_text}\u202C"
        
        # Determine recipient (IT manager mailbox from config, fallback to first IT manager's email)
        cfg = EmailConfig.get_active()
        recipient_email = None
        if cfg and cfg.username:
            recipient_email = cfg.username
        else:
            manager = User.objects.filter(role='it_manager').exclude(email='').first()
            if manager and manager.email:
                recipient_email = manager.email
        
        if recipient_email:
            msg["To"] = recipient_email
        else:
            print("❌ No recipient email found")
            return
        
        # Create HTML part
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)
        
        # Try to attach logo
        try:
            logo_path = os.path.join(settings.STATIC_ROOT, 'admin', 'img', 'white-pargsStar.webp')
            if os.path.exists(logo_path):
                with open(logo_path, 'rb') as f:
                    logo = MIMEImage(f.read())
                    logo.add_header('Content-ID', '<logo>')
                    msg.attach(logo)
        except Exception as e:
            print(f"⚠️ Could not attach logo: {e}")
        
        # Get email configuration
        cfg = EmailConfig.get_active()
        if not cfg:
            print("❌ No email configuration found")
            return
        
        smtp_host = cfg.host
        smtp_port = cfg.port
        smtp_user = cfg.username
        smtp_pass = cfg.password
        use_tls = cfg.use_tls
        use_ssl = cfg.use_ssl
        
        # Set From header
        msg["From"] = smtp_user if smtp_user else "noreply@pargasiran.com"
        
        # Send email via configured backend
        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port)
        try:
            if use_tls and not use_ssl:
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        finally:
            server.quit()
        print("✅ User management email sent successfully!")
        
    except Exception as e:
        print(f"❌ Failed to send user management email: {e}")

def create_user_management_email_template(action_type, user, actor):
    """Create a special email template for user management operations"""
    
    from django.utils import timezone
    
    # Get action display text
    action_display_map = {
        'create': 'ایجاد کاربر جدید',
        'update': 'ویرایش اطلاعات کاربر',
        'delete': 'حذف کاربر',
    }
    action_display = action_display_map.get(action_type, action_type)
    
    # Base template with logo and styling
    html_template = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="fa">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{action_display}</title>
        <style>
            body {{
                font-family: Tahoma, 'Segoe UI', Arial, sans-serif;
                margin: 0;
                padding: 0;
                background-color: #f5f5f5;
                direction: rtl;
                text-align: right;
                font-size: 18px;
                line-height: 1.7;
            }}
            .email-container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 10px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                overflow: hidden;
            }}
            .header {{
                background: linear-gradient(135deg, #007bff 0%, #0056b3 100%);
                padding: 30px 20px;
                text-align: center;
                color: white;
            }}
            .logo {{
                width: 80px;
                height: 80px;
                border-radius: 50%;
                margin-bottom: 15px;
                border: 3px solid rgba(255, 255, 255, 0.3);
            }}
            .header h1 {{
                margin: 0;
                font-size: 28px;
                font-weight: bold;
                margin-bottom: 5px;
            }}
            .header p {{
                margin: 0;
                font-size: 18px;
                opacity: 0.9;
            }}
            .content {{
                padding: 30px 20px;
                line-height: 1.8;
                direction: rtl;
                text-align: right;
            }}
            .user-info {{
                background-color: #f8f9fa;
                border-radius: 8px;
                padding: 20px;
                margin-bottom: 20px;
                border-right: 4px solid #007bff;
                font-size: 18px;
            }}
            .info-section {{
                background-color: #ffffff;
                border: 1px solid #e9ecef;
                border-radius: 8px;
                padding: 2px 20px;
                margin-bottom: 20px;
            }}
            .info-row {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 10px 0;
                font-size: 18px;
            }}
            .info-row:last-child {{
                border-bottom: none;
            }}
            .info-label {{
                font-weight: bold;
                color: #495057;
                min-width: 120px;
                font-size: 18px;
            }}
            .info-value {{
                color: #212529;
                text-align: left;
                font-size: 18px;
            }}
        </style>
    </head>
    <body>
        <div class="email-container">
            <div class="header">
                <img src="cid:logo" alt="لوگو" class="logo">
                <h1>{action_display}</h1>
                <p>سیستم مدیریت تیکت</p>
            </div>
            
            <div class="content">
                <div class="user-info">
                    <strong>👤 کاربر:</strong> <span dir="auto">{user.get_full_name() or user.username}</span>
                    <br>
                    <strong>🆔 کد پرسنلی:</strong> <span dir="auto">{user.employee_code}</span>
                    <br>
                    <strong>🏢 بخش:</strong> <span dir="auto">{user.get_department_display() if hasattr(user, 'get_department_display') else (user.department or 'نامشخص')}</span>
                    <br>
                    <strong>👨‍💼 نقش:</strong> <span dir="auto">{user.get_role_display()}</span>
                </div>
                
                <div class="info-section">
                    <div class="info-row">
                        <span class="info-label">نوع عملیات:</span>
                        <span class="info-value">{action_display}</span>
                    </div>
                    
                    <div class="info-row">
                        <span class="info-label">تاریخ و زمان:</span>
                        <span class="info-value">{get_iranian_datetime_full(timezone.now())}</span>
                    </div>
                </div>
    """
    
    # Note: Additional information section removed as requested
    
    # Close the template
    html_template += """
            </div>
        </div>
    </body>
    </html>
    """
    
    return html_template

from django.db.models import Count, Avg, Q, F, ExpressionWrapper, fields
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, ExtractHour
from django.utils import timezone
from datetime import timedelta, datetime
from .models import Ticket, User, Reply


class StatisticsService:
    """Service class for handling ticket system statistics and analytics"""
    
    def __init__(self, date_from=None, date_to=None):
        """
        Initialize the service with optional date filters
        
        Args:
            date_from: Start date for filtering (datetime)
            date_to: End date for filtering (datetime)
        """
        self.date_from = date_from or (timezone.now() - timedelta(days=30))
        self.date_to = date_to or timezone.now()
        
        # Base queryset excluding unapproved network access tickets
        self.base_queryset = Ticket.objects.filter(
            created_at__range=(self.date_from, self.date_to)
        ).exclude(
            category='access',
            access_approval_status__in=['pending', 'rejected']
        )
    
    def get_total_tickets(self):
        """Get total tickets count excluding unapproved network access tickets"""
        # Base queryset excluding unapproved network access tickets
        base_tickets = Ticket.objects.exclude(
            category='access',
            access_approval_status__in=['pending', 'rejected']
        )
        
        # Get current Iranian date
        now = timezone.now()
        iranian_now = jdatetime.datetime.fromgregorian(datetime=now)
        
        # Calculate Iranian week (Saturday to Friday)
        # In Iranian calendar, Saturday is weekday 0, Friday is weekday 6
        # This ensures the week runs from Saturday (شنبه) to Friday (جمعه)
        iranian_weekday = iranian_now.weekday()
        
        # Calculate days since last Saturday
        # Saturday = 0, Sunday = 1, ..., Friday = 6
        days_since_saturday = (iranian_weekday + 1) % 7
        if days_since_saturday == 0:
            days_since_saturday = 7  # If today is Saturday, we want 0 days since Saturday
        
        # Calculate start of Iranian week (last Saturday)
        iranian_week_start = iranian_now - timedelta(days=days_since_saturday - 1)
        iranian_week_start = iranian_week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Convert Iranian week start to Gregorian for database query
        gregorian_week_start = iranian_week_start.togregorian()
        # Ensure timezone awareness
        if gregorian_week_start.tzinfo is None:
            gregorian_week_start = timezone.make_aware(gregorian_week_start)
        
        # Calculate Iranian month start
        iranian_month_start = jdatetime.datetime(
            iranian_now.year, 
            iranian_now.month, 
            1, 
            hour=0, minute=0, second=0, microsecond=0
        )
        gregorian_month_start = iranian_month_start.togregorian()
        # Ensure timezone awareness
        if gregorian_month_start.tzinfo is None:
            gregorian_month_start = timezone.make_aware(gregorian_month_start)
        
        return {
            'total': base_tickets.count(),
            'today': base_tickets.filter(created_at__date=now.date()).count(),
            'this_week': base_tickets.filter(
                created_at__gte=gregorian_week_start
            ).count(),
            'this_month': base_tickets.filter(
                created_at__gte=gregorian_month_start
            ).count(),
        }
    
    def get_ticket_status_breakdown(self):
        """Get tickets grouped by status"""
        status_stats = self.base_queryset.values('status').annotate(
            count=Count('id')
        ).order_by('status')
        
        # Add status display names and colors
        status_choices = dict(Ticket.STATUS_CHOICES)
        for stat in status_stats:
            stat['status_display'] = status_choices.get(stat['status'], stat['status'])
            stat['status_color'] = get_status_color(stat['status'])
        
        return list(status_stats)
    
    def get_ticket_creation_trend(self, period='daily', days=30):
        """Get ticket creation trend over time"""
        if period == 'daily':
            trunc_func = TruncDate
            days_back = days
        elif period == 'weekly':
            trunc_func = TruncWeek
            days_back = days * 7
        elif period == 'monthly':
            trunc_func = TruncMonth
            days_back = days * 30
        else:
            trunc_func = TruncDate
            days_back = days
        
        start_date = timezone.now() - timedelta(days=days_back)
        
        trend_data = Ticket.objects.filter(
            created_at__gte=start_date
        ).exclude(
            category='access',
            access_approval_status__in=['pending', 'rejected']
        ).annotate(
            period=trunc_func('created_at')
        ).values('period').annotate(
            count=Count('id')
        ).order_by('period')
        
        return list(trend_data)
    
    def get_average_response_time(self):
        """Calculate average response and resolution times"""
        # Get tickets with at least one reply
        tickets_with_replies = self.base_queryset.filter(replies__isnull=False).distinct()
        
        response_times = []
        resolution_times = []
        
        for ticket in tickets_with_replies:
            # First response time
            first_reply = ticket.replies.order_by('created_at').first()
            if first_reply:
                response_time = (first_reply.created_at - ticket.created_at).total_seconds() / 3600  # hours
                response_times.append(response_time)
            
            # Resolution time (if resolved)
            if ticket.status in ['resolved', 'closed']:
                resolution_time = (ticket.updated_at - ticket.created_at).total_seconds() / 3600  # hours
                resolution_times.append(resolution_time)
        
        return {
            'avg_response_time': sum(response_times) / len(response_times) if response_times else 0,
            'avg_resolution_time': sum(resolution_times) / len(resolution_times) if resolution_times else 0,
            'response_count': len(response_times),
            'resolution_count': len(resolution_times),
        }
    
    def get_agent_performance(self):
        """Get performance statistics for each agent"""
        agents = User.objects.filter(role__in=['technician'])
        agent_stats = []
        
        for agent in agents:
            # Tickets assigned to this agent
            assigned_tickets = self.base_queryset.filter(assigned_to=agent)
            
            # Replies by this agent
            agent_replies = Reply.objects.filter(
                author=agent,
                created_at__range=(self.date_from, self.date_to)
            )
            
            # Calculate response times for this agent
            response_times = []
            for reply in agent_replies:
                ticket = reply.ticket
                # Find the first reply to this ticket
                first_reply = ticket.replies.order_by('created_at').first()
                if first_reply and first_reply.author == agent:
                    response_time = (reply.created_at - ticket.created_at).total_seconds() / 3600
                    response_times.append(response_time)
            
            avg_response_time = sum(response_times) / len(response_times) if response_times else 0
            
            # Resolution rate
            resolved_tickets = assigned_tickets.filter(status__in=['resolved', 'closed'])
            resolution_rate = (resolved_tickets.count() / assigned_tickets.count() * 100) if assigned_tickets.count() > 0 else 0
            
            agent_stats.append({
                'agent': agent,
                'agent_name': agent.get_full_name() or agent.username,
                'agent_role': agent.role,
                'tickets_assigned': assigned_tickets.count(),
                'tickets_resolved': resolved_tickets.count(),
                'replies_count': agent_replies.count(),
                'avg_response_time': avg_response_time,
                'resolution_rate': resolution_rate,
            })
        
        # Sort by resolution rate (best first)
        agent_stats.sort(key=lambda x: x['resolution_rate'], reverse=True)
        return agent_stats
    
    def get_user_statistics(self):
        """Get user-related statistics"""
        total_users = User.objects.count()
        users_with_tickets = User.objects.filter(created_tickets__isnull=False).distinct().count()
        
        # Active users in last 7 days
        seven_days_ago = timezone.now() - timedelta(days=7)
        active_users = User.objects.filter(
            Q(created_tickets__created_at__gte=seven_days_ago) |
            Q(replies__created_at__gte=seven_days_ago)
        ).distinct().count()
        
        return {
            'total_users': total_users,
            'users_with_tickets': users_with_tickets,
            'active_users_7_days': active_users,
            'user_engagement_rate': (users_with_tickets / total_users * 100) if total_users > 0 else 0,
        }
    
    def get_category_statistics(self):
        """Get ticket statistics by category"""
        category_stats = self.base_queryset.values('category').annotate(
            count=Count('id')
        ).order_by('-count')
        
        # Add category display names
        category_choices = dict(Ticket.CATEGORY_CHOICES)
        for stat in category_stats:
            stat['category_display'] = category_choices.get(stat['category'], stat['category'])
        
        return list(category_stats)
    
    def get_priority_statistics(self):
        """Get ticket statistics by priority"""
        priority_stats = self.base_queryset.values('priority').annotate(
            count=Count('id')
        ).order_by('-count')
        
        # Add priority display names and colors
        priority_choices = dict(Ticket.PRIORITY_CHOICES)
        for stat in priority_stats:
            stat['priority_display'] = priority_choices.get(stat['priority'], stat['priority'])
            stat['priority_color'] = get_priority_color(stat['priority'])
        
        return list(priority_stats)
    
    def get_high_priority_tickets(self):
        """Get open high-priority tickets (high/urgent, any assignment)"""
        # Base query for high priority tickets
        high_priority_tickets = Ticket.objects.filter(
            priority__in=['high', 'urgent'],
            status='open'
        )
        
        # Exclude network access tickets that are not approved
        high_priority_tickets = high_priority_tickets.exclude(
            category='access',
            access_approval_status__in=['pending', 'rejected']
        )
        
        high_priority_tickets = high_priority_tickets.order_by('-created_at')
        
        return {
            'count': high_priority_tickets.count(),
            'tickets': high_priority_tickets[:10],  # Top 10 for display
        }
    
    def get_first_contact_resolution_rate(self):
        """Calculate first contact resolution rate"""
        # Get tickets that were resolved
        resolved_tickets = self.base_queryset.filter(status__in=['resolved', 'closed'])
        
        first_contact_resolved = 0
        total_resolved = resolved_tickets.count()
        
        for ticket in resolved_tickets:
            # Check if ticket was resolved with first reply
            replies = ticket.replies.order_by('created_at')
            if replies.exists():
                first_reply = replies.first()
                # If the ticket was resolved after the first reply
                if ticket.updated_at <= first_reply.created_at + timedelta(hours=24):
                    first_contact_resolved += 1
        
        fcr_rate = (first_contact_resolved / total_resolved * 100) if total_resolved > 0 else 0
        
        return {
            'fcr_rate': fcr_rate,
            'first_contact_resolved': first_contact_resolved,
            'total_resolved': total_resolved,
        }
    
    def get_hourly_distribution(self):
        """Get today's ticket creation distribution by hour in Iranian time (auto-resets daily at 00:00 Asia/Tehran).

        Returns 24 buckets (0-23) with zero counts where no tickets exist, ensuring a consistent chart.
        """
        from django.utils import timezone
        from django.db.models.functions import ExtractHour
        from zoneinfo import ZoneInfo

        tehran_tz = ZoneInfo('Asia/Tehran')

        # Determine Tehran today's midnight and convert to UTC for DB filtering
        now_tehran = timezone.now().astimezone(tehran_tz)
        tehran_midnight = now_tehran.replace(hour=0, minute=0, second=0, microsecond=0)
        midnight_utc = tehran_midnight.astimezone(timezone.utc)

        # Base queryset for today only, excluding unapproved access tickets
        today_queryset = Ticket.objects.filter(
            created_at__gte=midnight_utc
        ).exclude(
            category='access',
            access_approval_status__in=['pending', 'rejected']
        )

        # Aggregate by Tehran hour of creation
        raw_stats = today_queryset.annotate(
            hour=ExtractHour('created_at', tzinfo=tehran_tz)
        ).values('hour').annotate(
            count=Count('id')
        )

        # Normalize to 24 buckets
        hour_to_count = {i: 0 for i in range(24)}
        for row in raw_stats:
            hour = row.get('hour')
            if hour is None:
                continue
            # Ensure hour is within 0-23
            if 0 <= int(hour) <= 23:
                hour_to_count[int(hour)] = row.get('count', 0)

        return [
            {'hour': h, 'count': hour_to_count[h]}
            for h in range(24)
        ]
    
    def get_inter_department_statistics(self):
        """Get statistics about tickets exchanged between departments"""
        from .models import Department
        
        # Get all tickets with source and target departments
        tickets = self.base_queryset.select_related('created_by__department', 'target_department')
        
        # Statistics by source department (where ticket was created)
        source_dept_stats = tickets.values(
            'created_by__department__name'
        ).annotate(
            count=Count('id')
        ).order_by('-count')
        
        # Statistics by target department (where ticket was sent)
        target_dept_stats = tickets.exclude(
            target_department__isnull=True
        ).values(
            'target_department__name'
        ).annotate(
            count=Count('id')
        ).order_by('-count')
        
        # Department-to-department flow (source -> target)
        dept_flows = []
        for ticket in tickets.exclude(target_department__isnull=True):
            source_dept = ticket.created_by.department.name if ticket.created_by.department else 'بدون بخش'
            target_dept = ticket.target_department.name if ticket.target_department else 'بدون بخش'
            dept_flows.append({
                'source': source_dept,
                'target': target_dept
            })
        
        # Count flows
        flow_counts = {}
        for flow in dept_flows:
            key = f"{flow['source']} -> {flow['target']}"
            flow_counts[key] = flow_counts.get(key, 0) + 1
        
        # Convert to list sorted by count with separate source and target
        flow_list = []
        for k, v in sorted(flow_counts.items(), key=lambda x: x[1], reverse=True)[:20]:
            parts = k.split(' -> ')
            flow_list.append({
                'source': parts[0] if len(parts) > 0 else 'بدون بخش',
                'target': parts[1] if len(parts) > 1 else 'بدون بخش',
                'count': v
            })
        
        return {
            'source_department_stats': list(source_dept_stats),
            'target_department_stats': list(target_dept_stats),
            'department_flows': flow_list,  # Top 20 flows
        }
    
    def get_department_priority_status_breakdown(self):
        """Get priority and status breakdown by department"""
        from .models import Department
        
        # Get all departments
        departments = Department.objects.filter(is_active=True)
        
        dept_breakdown = []
        
        for dept in departments:
            # Tickets created by users in this department
            dept_tickets_created = self.base_queryset.filter(
                created_by__department=dept
            )
            
            # Tickets sent to this department
            dept_tickets_received = self.base_queryset.filter(
                target_department=dept
            )
            
            # Priority breakdown for created tickets
            priority_breakdown_created = dept_tickets_created.values('priority').annotate(
                count=Count('id')
            )
            
            # Priority breakdown for received tickets
            priority_breakdown_received = dept_tickets_received.values('priority').annotate(
                count=Count('id')
            )
            
            # Status breakdown for created tickets
            status_breakdown_created = dept_tickets_created.values('status').annotate(
                count=Count('id')
            )
            
            # Status breakdown for received tickets
            status_breakdown_received = dept_tickets_received.values('status').annotate(
                count=Count('id')
            )
            
            dept_breakdown.append({
                'department': dept.name,
                'department_id': dept.id,
                'tickets_created': dept_tickets_created.count(),
                'tickets_received': dept_tickets_received.count(),
                'priority_breakdown_created': list(priority_breakdown_created),
                'priority_breakdown_received': list(priority_breakdown_received),
                'status_breakdown_created': list(status_breakdown_created),
                'status_breakdown_received': list(status_breakdown_received),
            })
        
        return dept_breakdown
    
    def get_department_performance_metrics(self):
        """Get performance metrics for each department"""
        from .models import Department
        
        departments = Department.objects.filter(is_active=True)
        dept_performance = []
        
        for dept in departments:
            # Tickets received by this department
            received_tickets = self.base_queryset.filter(target_department=dept)
            
            # Calculate average response time for received tickets
            response_times = []
            resolution_times = []
            
            for ticket in received_tickets:
                if ticket.replies.exists():
                    first_reply = ticket.replies.order_by('created_at').first()
                    if first_reply:
                        response_time = (first_reply.created_at - ticket.created_at).total_seconds() / 3600
                        response_times.append(response_time)
                
                if ticket.status in ['resolved', 'closed']:
                    resolution_time = (ticket.updated_at - ticket.created_at).total_seconds() / 3600
                    resolution_times.append(resolution_time)
            
            avg_response = sum(response_times) / len(response_times) if response_times else 0
            avg_resolution = sum(resolution_times) / len(resolution_times) if resolution_times else 0
            
            # Resolution rate
            resolved_count = received_tickets.filter(status__in=['resolved', 'closed']).count()
            resolution_rate = (resolved_count / received_tickets.count() * 100) if received_tickets.count() > 0 else 0
            
            dept_performance.append({
                'department': dept.name,
                'department_id': dept.id,
                'total_received': received_tickets.count(),
                'resolved_count': resolved_count,
                'open_count': received_tickets.filter(status='open').count(),
                'in_progress_count': received_tickets.filter(status='in_progress').count(),
                'avg_response_time_hours': avg_response,
                'avg_resolution_time_hours': avg_resolution,
                'resolution_rate': resolution_rate,
            })
        
        return sorted(dept_performance, key=lambda x: x['total_received'], reverse=True)
    
    def get_comprehensive_statistics(self):
        """Get all statistics in one call"""
        return {
            'total_tickets': self.get_total_tickets(),
            'status_breakdown': self.get_ticket_status_breakdown(),
            'creation_trend': self.get_ticket_creation_trend(),
            'response_times': self.get_average_response_time(),
            'agent_performance': self.get_agent_performance(),
            'user_stats': self.get_user_statistics(),
            'category_stats': self.get_category_statistics(),
            'priority_stats': self.get_priority_statistics(),
            'high_priority': self.get_high_priority_tickets(),
            'fcr_rate': self.get_first_contact_resolution_rate(),
            'hourly_distribution': self.get_hourly_distribution(),
            'inter_department_stats': self.get_inter_department_statistics(),
            'department_priority_status': self.get_department_priority_status_breakdown(),
            'department_performance': self.get_department_performance_metrics(),
            'date_range': {
                'from': self.date_from,
                'to': self.date_to,
            }
        } 

def get_filtered_replies_for_user(ticket, user):
    """
    Get replies for a ticket based on user permissions.
    Private replies are only visible to the ticket creator and IT managers.
    Team leads can see that private replies exist but not their content.
    
    Args:
        ticket: Ticket object
        user: User object requesting the replies
        
    Returns:
        QuerySet: Filtered replies based on user permissions
    """
    from .models import Reply
    
    if user.role == 'it_manager':
        # IT managers can see all replies including private ones
        return ticket.replies.all()
    elif user.role == 'technician':
        # Technicians can see all replies (no private replies for them)
        return ticket.replies.filter(is_private=False)
    elif user.role == 'employee':
        if user.department_role == 'manager':
            # General managers can see all replies
            return ticket.replies.all()
        elif user.department_role == 'senior':
            # Team leads can see all replies but private content is hidden
            return ticket.replies.all()
        else:
            # Regular employees can only see their own private replies and all public replies
            from django.db.models import Q
            return ticket.replies.filter(
                Q(is_private=False) | 
                Q(is_private=True, ticket__created_by=user)
            )
    else:
        # Default fallback - no private replies
        return ticket.replies.filter(is_private=False)

def can_view_private_reply_content(reply, user):
    """
    Check if a user can view the full content of a private reply.
    
    Args:
        reply: Reply object
        user: User object
        
    Returns:
        bool: True if user can view private reply content, False otherwise
    """
    if not reply.is_private:
        return True
    
    if user.role == 'it_manager':
        return True
    elif user.role == 'employee' and user.department_role == 'manager':
        return True
    elif user.role == 'employee' and reply.ticket.created_by == user:
        return True
    else:
        return False 