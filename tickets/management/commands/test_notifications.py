from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from tickets.models import Notification
from tickets.services import create_notification

User = get_user_model()

class Command(BaseCommand):
    help = 'Test notification creation and display'

    def handle(self, *args, **options):
        # Get IT managers
        it_managers = User.objects.filter(role='it_manager')
        self.stdout.write(f"Found {it_managers.count()} IT managers")
        
        for manager in it_managers:
            self.stdout.write(f"  - {manager.get_full_name()} (ID: {manager.id})")
        
        if not it_managers.exists():
            self.stdout.write(self.style.ERROR("No IT managers found!"))
            return
        
        # Test notification creation
        manager = it_managers.first()
        self.stdout.write(f"\nTesting notification creation for {manager.get_full_name()}")
        
        # Create a test notification
        notification = create_notification(
            recipient=manager,
            title="Test Notification",
            message="This is a test notification to verify the system is working",
            notification_type='ticket_created',
            category='tickets'
        )
        
        if notification:
            self.stdout.write(self.style.SUCCESS(f"✅ Test notification created successfully: {notification.title}"))
        else:
            self.stdout.write(self.style.ERROR("❌ Failed to create test notification"))
            return
        
        # Check unread count
        unread_count = Notification.objects.filter(recipient=manager, is_read=False).count()
        self.stdout.write(f"Unread notifications count: {unread_count}")
        
        # List all notifications for this manager
        all_notifications = Notification.objects.filter(recipient=manager).order_by('-created_at')
        self.stdout.write(f"\nAll notifications for {manager.get_full_name()}:")
        for notif in all_notifications[:5]:
            status = "UNREAD" if not notif.is_read else "READ"
            self.stdout.write(f"  - {notif.title} ({status}) - {notif.created_at}")
        
        # Test template tag
        from tickets.templatetags.notifications_tags import unread_notifications_count
        from django.template import Context, Template
        
        # Create a mock context
        class MockRequest:
            def __init__(self, user):
                self.user = user
        
        mock_context = {'request': MockRequest(manager)}
        count = unread_notifications_count(mock_context)
        self.stdout.write(f"Template tag result: {count}")
        
        if count > 0:
            self.stdout.write(self.style.SUCCESS("✅ Notification system is working correctly!"))
        else:
            self.stdout.write(self.style.ERROR("❌ Template tag is not returning the correct count"))