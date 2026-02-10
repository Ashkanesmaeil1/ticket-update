"""
Management command to normalize National ID and Employee Code for all users.

This command converts Persian/Arabic numerals to English numerals in existing
user records to ensure data consistency and prevent authentication failures.

Usage:
    python manage.py normalize_user_identifiers
    python manage.py normalize_user_identifiers --dry-run  # Preview changes without saving
    python manage.py normalize_user_identifiers --verbose  # Show detailed output
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from tickets.models import User
from tickets.utils import normalize_national_id, normalize_employee_code
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Normalize National ID and Employee Code for all users (convert Persian/Arabic numerals to English)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without saving to database',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output for each user',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        verbose = options['verbose']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be saved'))
        
        users = User.objects.all()
        total_users = users.count()
        updated_count = 0
        errors = []
        
        self.stdout.write(f'Processing {total_users} users...')
        
        with transaction.atomic():
            for user in users:
                changes = []
                original_national_id = user.national_id
                original_employee_code = user.employee_code
                
                # Normalize National ID
                normalized_nid = normalize_national_id(user.national_id)
                if normalized_nid != original_national_id:
                    changes.append(f"National ID: '{original_national_id}' -> '{normalized_nid}'")
                    if not dry_run:
                        user.national_id = normalized_nid
                
                # Normalize Employee Code
                normalized_ec = normalize_employee_code(user.employee_code)
                if normalized_ec != original_employee_code:
                    changes.append(f"Employee Code: '{original_employee_code}' -> '{normalized_ec}'")
                    if not dry_run:
                        user.employee_code = normalized_ec
                
                # Save if there are changes
                if changes:
                    updated_count += 1
                    if verbose:
                        self.stdout.write(
                            f"User ID {user.id} ({user.get_full_name()}): {', '.join(changes)}"
                        )
                    
                    if not dry_run:
                        try:
                            # Use update_fields to avoid triggering full save
                            update_fields = []
                            if normalized_nid != original_national_id:
                                update_fields.append('national_id')
                            if normalized_ec != original_employee_code:
                                update_fields.append('employee_code')
                            
                            if update_fields:
                                User.objects.filter(pk=user.pk).update(
                                    **{field: getattr(user, field) for field in update_fields}
                                )
                        except Exception as e:
                            error_msg = f"Error updating user ID {user.id}: {str(e)}"
                            errors.append(error_msg)
                            self.stdout.write(self.style.ERROR(error_msg))
                            logger.error(error_msg, exc_info=True)
            
            if dry_run:
                # Rollback transaction in dry-run mode
                transaction.set_rollback(True)
        
        # Summary
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Summary:'))
        self.stdout.write(f'  Total users processed: {total_users}')
        self.stdout.write(f'  Users updated: {updated_count}')
        self.stdout.write(f'  Users unchanged: {total_users - updated_count}')
        
        if errors:
            self.stdout.write(self.style.ERROR(f'  Errors: {len(errors)}'))
            for error in errors:
                self.stdout.write(self.style.ERROR(f'    - {error}'))
        
        if dry_run:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('This was a dry run. No changes were saved.'))
            self.stdout.write(self.style.WARNING('Run without --dry-run to apply changes.'))
        else:
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('Normalization completed successfully!'))





