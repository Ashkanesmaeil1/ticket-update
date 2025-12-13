from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from tickets.models import Ticket, Reply
from django.utils import timezone
from datetime import timedelta

User = get_user_model()

class Command(BaseCommand):
    help = 'Set up initial data for the ticket system'

    def handle(self, *args, **options):
        self.stdout.write('Setting up initial data...')
        
        # Create IT Manager
        it_manager, created = User.objects.get_or_create(
            username='it_manager',
            defaults={
                'email': 'it.manager@company.com',
                'first_name': 'John',
                'last_name': 'Manager',
                'national_id': '12345678901234567890',
                'employee_code': 'IT001',
                'role': 'it_manager',
                'phone': '+1234567890',
                'department': None,
                'is_staff': True,
                'is_superuser': True,
            }
        )
        if created:
            it_manager.set_password('password123')
            it_manager.save()
            self.stdout.write(self.style.SUCCESS('Created IT Manager'))
        else:
            self.stdout.write('IT Manager already exists')
        
        # Create Technicians
        technician1, created = User.objects.get_or_create(
            username='tech1',
            defaults={
                'email': 'tech1@company.com',
                'first_name': 'Sarah',
                'last_name': 'Technician',
                'national_id': '12345678901234567891',
                'employee_code': 'TECH001',
                'role': 'technician',
                'phone': '+1234567891',
                'department': 'IT Support',
                'assigned_by': it_manager,
            }
        )
        if created:
            technician1.set_password('password123')
            technician1.save()
            self.stdout.write(self.style.SUCCESS('Created Technician 1'))
        else:
            self.stdout.write('Technician 1 already exists')
        
        technician2, created = User.objects.get_or_create(
            username='tech2',
            defaults={
                'email': 'tech2@company.com',
                'first_name': 'Mike',
                'last_name': 'Support',
                'national_id': '12345678901234567892',
                'employee_code': 'TECH002',
                'role': 'technician',
                'phone': '+1234567892',
                'department': 'IT Support',
                'assigned_by': it_manager,
            }
        )
        if created:
            technician2.set_password('password123')
            technician2.save()
            self.stdout.write(self.style.SUCCESS('Created Technician 2'))
        else:
            self.stdout.write('Technician 2 already exists')
        
        # Create Employees
        employee1, created = User.objects.get_or_create(
            username='emp1',
            defaults={
                'email': 'emp1@company.com',
                'first_name': 'Alice',
                'last_name': 'Johnson',
                'national_id': '12345678901234567893',
                'employee_code': 'EMP001',
                'role': 'employee',
                'phone': '+1234567893',
                'department': 'Marketing',
            }
        )
        if created:
            employee1.set_password('password123')
            employee1.save()
            self.stdout.write(self.style.SUCCESS('Created Employee 1'))
        else:
            self.stdout.write('Employee 1 already exists')
        
        employee2, created = User.objects.get_or_create(
            username='emp2',
            defaults={
                'email': 'emp2@company.com',
                'first_name': 'Bob',
                'last_name': 'Smith',
                'national_id': '12345678901234567894',
                'employee_code': 'EMP002',
                'role': 'employee',
                'phone': '+1234567894',
                'department': 'Sales',
            }
        )
        if created:
            employee2.set_password('password123')
            employee2.save()
            self.stdout.write(self.style.SUCCESS('Created Employee 2'))
        else:
            self.stdout.write('Employee 2 already exists')
        
        employee3, created = User.objects.get_or_create(
            username='emp3',
            defaults={
                'email': 'emp3@company.com',
                'first_name': 'Carol',
                'last_name': 'Davis',
                'national_id': '12345678901234567895',
                'employee_code': 'EMP003',
                'role': 'employee',
                'phone': '+1234567895',
                'department': 'HR',
            }
        )
        if created:
            employee3.set_password('password123')
            employee3.save()
            self.stdout.write(self.style.SUCCESS('Created Employee 3'))
        else:
            self.stdout.write('Employee 3 already exists')
        
        # Create sample tickets
        if not Ticket.objects.exists():
            # Ticket 1 - Hardware issue
            ticket1 = Ticket.objects.create(
                title='Computer not turning on',
                description='My computer suddenly stopped working. It won\'t turn on when I press the power button. I tried different power outlets but it still doesn\'t work.',
                category='hardware',
                priority='high',
                status='open',
                created_by=employee1,
                created_at=timezone.now() - timedelta(days=2)
            )
            
            # Ticket 2 - Software issue
            ticket2 = Ticket.objects.create(
                title='Email client not working',
                description='I can\'t send or receive emails through Outlook. It keeps showing an error message about connection timeout.',
                category='software',
                priority='medium',
                status='in_progress',
                created_by=employee2,
                assigned_to=technician1,
                created_at=timezone.now() - timedelta(days=1)
            )
            
            # Ticket 3 - Network issue
            ticket3 = Ticket.objects.create(
                title='Slow internet connection',
                description='The internet is extremely slow today. It takes forever to load any website. This is affecting my work productivity.',
                category='network',
                priority='urgent',
                status='open',
                created_by=employee3,
                created_at=timezone.now() - timedelta(hours=6)
            )
            
            # Ticket 4 - Access issue
            ticket4 = Ticket.objects.create(
                title='Cannot access shared folder',
                description='I need access to the Marketing shared folder but I get a permission denied error. Can someone help me get the proper access?',
                category='access',
                priority='medium',
                status='resolved',
                created_by=employee1,
                assigned_to=technician2,
                created_at=timezone.now() - timedelta(days=3),
                resolved_at=timezone.now() - timedelta(days=1)
            )
            
            # Add replies to tickets
            Reply.objects.create(
                ticket=ticket2,
                author=technician1,
                content='I can see the issue with your Outlook configuration. Let me help you fix this. Can you try restarting Outlook first?'
            )
            
            Reply.objects.create(
                ticket=ticket2,
                author=employee2,
                content='I restarted Outlook but the issue persists. The error message still appears.'
            )
            
            Reply.objects.create(
                ticket=ticket2,
                author=technician1,
                content='I\'ll need to check your email server settings. Can you provide me with your email address so I can verify the configuration?'
            )
            
            Reply.objects.create(
                ticket=ticket4,
                author=technician2,
                content='I\'ve granted you access to the Marketing shared folder. You should be able to access it now. Please try again and let me know if you still have issues.'
            )
            
            Reply.objects.create(
                ticket=ticket4,
                author=employee1,
                content='Perfect! I can access the folder now. Thank you for your help!'
            )
            
            self.stdout.write(self.style.SUCCESS('Created sample tickets and replies'))
        else:
            self.stdout.write('Sample tickets already exist')
        
        self.stdout.write(self.style.SUCCESS('Setup completed successfully!'))
        self.stdout.write('\nLogin Credentials:')
        self.stdout.write('IT Manager: National ID: 12345678901234567890, Employee Code: IT001')
        self.stdout.write('Technician 1: National ID: 12345678901234567891, Employee Code: TECH001')
        self.stdout.write('Technician 2: National ID: 12345678901234567892, Employee Code: TECH002')
        self.stdout.write('Employee 1: National ID: 12345678901234567893, Employee Code: EMP001')
        self.stdout.write('Employee 2: National ID: 12345678901234567894, Employee Code: EMP002')
        self.stdout.write('Employee 3: National ID: 12345678901234567895, Employee Code: EMP003')
        self.stdout.write('\nAll users have password: password123') 