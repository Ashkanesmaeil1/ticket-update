"""
Management command to inspect user identifiers for debugging authentication issues.

This command helps diagnose authentication problems by showing:
- Raw database values (including hidden characters)
- Normalized values
- Identity parity: username vs national_id (should match after admin edits)
- Comparison with login query
- Session information

Usage (Docker):
    docker compose exec web python manage.py inspect_user_identifiers
    docker compose exec web python manage.py inspect_user_identifiers --national-id 1234567890
    docker compose exec web python manage.py inspect_user_identifiers --employee-code 1234
    docker compose exec web python manage.py inspect_user_identifiers --user-id 1
"""

from django.core.management.base import BaseCommand
from django.contrib.sessions.models import Session
from django.utils import timezone
from tickets.models import User
from tickets.utils import normalize_national_id, normalize_employee_code
import sys


class Command(BaseCommand):
    help = 'Inspect user identifiers for debugging authentication issues'

    def add_arguments(self, parser):
        parser.add_argument(
            '--national-id',
            type=str,
            help='Inspect user by National ID',
        )
        parser.add_argument(
            '--employee-code',
            type=str,
            help='Inspect user by Employee Code',
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Inspect user by User ID',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Show all users with potential issues (non-normalized identifiers)',
        )

    def handle(self, *args, **options):
        if options['all']:
            self.inspect_all_users()
        elif options['national_id']:
            self.inspect_by_national_id(options['national_id'])
        elif options['employee_code']:
            self.inspect_by_employee_code(options['employee_code'])
        elif options['user_id']:
            self.inspect_by_user_id(options['user_id'])
        else:
            self.stdout.write(self.style.ERROR('Please specify --national-id, --employee-code, --user-id, or --all'))
            self.stdout.write('Use --help for usage information')
            sys.exit(1)

    def inspect_by_national_id(self, national_id):
        """Inspect user by National ID"""
        normalized = normalize_national_id(national_id)
        
        self.stdout.write(self.style.SUCCESS(f'\n=== Inspecting by National ID ==='))
        self.stdout.write(f'Input: {repr(national_id)}')
        self.stdout.write(f'Normalized: {repr(normalized)}')
        self.stdout.write('')
        
        # Try to find user with raw value
        try:
            user_raw = User.objects.get(national_id=national_id)
            self.stdout.write(self.style.SUCCESS(f'✓ Found user with RAW National ID: {repr(national_id)}'))
            self.display_user_details(user_raw, 'RAW')
        except User.DoesNotExist:
            self.stdout.write(self.style.WARNING(f'✗ No user found with RAW National ID: {repr(national_id)}'))
        
        # Try to find user with normalized value
        if normalized != national_id:
            try:
                user_norm = User.objects.get(national_id=normalized)
                self.stdout.write(self.style.SUCCESS(f'✓ Found user with NORMALIZED National ID: {repr(normalized)}'))
                self.display_user_details(user_norm, 'NORMALIZED')
            except User.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'✗ No user found with NORMALIZED National ID: {repr(normalized)}'))

    def inspect_by_employee_code(self, employee_code):
        """Inspect user by Employee Code"""
        normalized = normalize_employee_code(employee_code)
        
        self.stdout.write(self.style.SUCCESS(f'\n=== Inspecting by Employee Code ==='))
        self.stdout.write(f'Input: {repr(employee_code)}')
        self.stdout.write(f'Normalized: {repr(normalized)}')
        self.stdout.write('')
        
        # Try to find user with raw value
        try:
            user_raw = User.objects.get(employee_code=employee_code)
            self.stdout.write(self.style.SUCCESS(f'✓ Found user with RAW Employee Code: {repr(employee_code)}'))
            self.display_user_details(user_raw, 'RAW')
        except User.DoesNotExist:
            self.stdout.write(self.style.WARNING(f'✗ No user found with RAW Employee Code: {repr(employee_code)}'))
        
        # Try to find user with normalized value
        if normalized != employee_code:
            try:
                user_norm = User.objects.get(employee_code=normalized)
                self.stdout.write(self.style.SUCCESS(f'✓ Found user with NORMALIZED Employee Code: {repr(normalized)}'))
                self.display_user_details(user_norm, 'NORMALIZED')
            except User.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'✗ No user found with NORMALIZED Employee Code: {repr(normalized)}'))

    def inspect_by_user_id(self, user_id):
        """Inspect user by User ID"""
        try:
            user = User.objects.get(pk=user_id)
            self.display_user_details(user, 'FULL')
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User with ID {user_id} not found'))

    def inspect_all_users(self):
        """Inspect all users for potential issues"""
        users = User.objects.all()
        issues_found = []
        
        self.stdout.write(self.style.SUCCESS(f'\n=== Inspecting All Users ==='))
        self.stdout.write(f'Total users: {users.count()}\n')
        
        for user in users:
            issues = []
            
            # Check if National ID needs normalization
            normalized_nid = normalize_national_id(user.national_id)
            if normalized_nid != user.national_id:
                issues.append(f"National ID: {repr(user.national_id)} -> {repr(normalized_nid)}")
            
            # Check if Employee Code needs normalization
            normalized_ec = normalize_employee_code(user.employee_code)
            if normalized_ec != user.employee_code:
                issues.append(f"Employee Code: {repr(user.employee_code)} -> {repr(normalized_ec)}")
            
            if issues:
                issues_found.append((user, issues))
        
        if issues_found:
            self.stdout.write(self.style.WARNING(f'Found {len(issues_found)} user(s) with potential issues:\n'))
            for user, issues in issues_found:
                self.stdout.write(f'User ID {user.id}: {user.get_full_name()}')
                for issue in issues:
                    self.stdout.write(f'  - {issue}')
                self.stdout.write('')
        else:
            self.stdout.write(self.style.SUCCESS('✓ All users have normalized identifiers'))

    def display_user_details(self, user, mode='FULL'):
        """Display detailed information about a user"""
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'User Details (ID: {user.id}):'))
        self.stdout.write(f'  Full Name: {user.get_full_name()}')
        self.stdout.write(f'  Username: {repr(user.username)}')
        self.stdout.write(f'  Email: {user.email}')
        # Identity parity: username should equal national_id for login/AdminModelBackend
        if user.national_id and user.username != user.national_id:
            self.stdout.write(self.style.WARNING(f'  ⚠ Username != National ID (sync may be needed)'))
        else:
            self.stdout.write(self.style.SUCCESS(f'  ✓ Username matches National ID (identity parity)'))
        self.stdout.write('')
        
        # National ID details
        normalized_nid = normalize_national_id(user.national_id)
        self.stdout.write(f'  National ID:')
        self.stdout.write(f'    Raw (repr): {repr(user.national_id)}')
        self.stdout.write(f'    Length: {len(user.national_id)}')
        self.stdout.write(f'    Normalized: {repr(normalized_nid)}')
        if normalized_nid != user.national_id:
            self.stdout.write(self.style.WARNING(f'    ⚠ Needs normalization!'))
        else:
            self.stdout.write(self.style.SUCCESS(f'    ✓ Already normalized'))
        
        # Employee Code details
        normalized_ec = normalize_employee_code(user.employee_code)
        self.stdout.write(f'  Employee Code:')
        self.stdout.write(f'    Raw (repr): {repr(user.employee_code)}')
        self.stdout.write(f'    Length: {len(user.employee_code)}')
        self.stdout.write(f'    Normalized: {repr(normalized_ec)}')
        if normalized_ec != user.employee_code:
            self.stdout.write(self.style.WARNING(f'    ⚠ Needs normalization!'))
        else:
            self.stdout.write(self.style.SUCCESS(f'    ✓ Already normalized'))
        
        # Password hash status
        self.stdout.write(f'  Password:')
        if user.password:
            self.stdout.write(f'    Hash exists: ✓ (Length: {len(user.password)})')
            self.stdout.write(f'    Hash preview: {user.password[:20]}...')
        else:
            self.stdout.write(self.style.WARNING(f'    ⚠ No password hash!'))
        
        # Active status
        self.stdout.write(f'  Status:')
        self.stdout.write(f'    Active: {"✓" if user.is_active else "✗"}')
        self.stdout.write(f'    Staff: {"✓" if user.is_staff else "✗"}')
        self.stdout.write(f'    Superuser: {"✓" if user.is_superuser else "✗"}')
        
        # Session information
        if mode == 'FULL':
            self.display_session_info(user)
        
        # Authentication test
        self.stdout.write('')
        self.stdout.write('  Authentication Test:')
        from tickets.backends import NationalIDEmployeeCodeBackend
        backend = NationalIDEmployeeCodeBackend()
        
        # Test with normalized values
        auth_user = backend.authenticate(
            None,
            national_id=normalized_nid,
            employee_code=normalized_ec
        )
        if auth_user and auth_user.pk == user.pk:
            self.stdout.write(self.style.SUCCESS(f'    ✓ Authentication would succeed with normalized values'))
        else:
            self.stdout.write(self.style.ERROR(f'    ✗ Authentication would FAIL with normalized values'))
        
        # Test with raw values (if different)
        if normalized_nid != user.national_id or normalized_ec != user.employee_code:
            auth_user_raw = backend.authenticate(
                None,
                national_id=user.national_id,
                employee_code=user.employee_code
            )
            if auth_user_raw and auth_user_raw.pk == user.pk:
                self.stdout.write(self.style.SUCCESS(f'    ✓ Authentication would succeed with raw values'))
            else:
                self.stdout.write(self.style.WARNING(f'    ⚠ Authentication would FAIL with raw values'))
        
        self.stdout.write('')

    def display_session_info(self, user):
        """Display active session information for the user"""
        try:
            active_sessions = Session.objects.filter(expire_date__gte=timezone.now())
            user_sessions = []
            
            for session in active_sessions:
                try:
                    session_data = session.get_decoded()
                    session_user_id = session_data.get('_auth_user_id')
                    if session_user_id and str(session_user_id) == str(user.pk):
                        user_sessions.append(session)
                except Exception:
                    continue
            
            self.stdout.write('')
            self.stdout.write(f'  Active Sessions: {len(user_sessions)}')
            if user_sessions:
                for i, session in enumerate(user_sessions, 1):
                    self.stdout.write(f'    Session {i}: {session.session_key[:20]}...')
                    self.stdout.write(f'      Expires: {session.expire_date}')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  Could not retrieve session info: {e}'))




