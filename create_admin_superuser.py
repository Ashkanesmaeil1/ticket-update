"""
Script to create the admin superuser with specific credentials.
Run this script once to create the admin superuser account.

Usage:
    python create_admin_superuser.py
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ticket_system.settings')
django.setup()

from tickets.models import User
from tickets.admin_security import ADMIN_SUPERUSER_USERNAME

# Admin credentials
ADMIN_SUPERUSER_PASSWORD = 'Xt2G6xCgGd8voj5'
ADMIN_SUPERUSER_NATIONAL_ID = '3689348171'  # Secure national ID for admin account
ADMIN_SUPERUSER_EMPLOYEE_CODE = '9437'  # Secure employee code for admin account

def create_admin_superuser():
    """Create or update the admin superuser account"""
    username = ADMIN_SUPERUSER_USERNAME
    password = ADMIN_SUPERUSER_PASSWORD
    national_id = ADMIN_SUPERUSER_NATIONAL_ID
    employee_code = ADMIN_SUPERUSER_EMPLOYEE_CODE
    
    # Check if user already exists by username
    user = User.objects.filter(username=username).first()
    
    # Also check if national_id or employee_code are already used by another user
    existing_by_national = User.objects.filter(national_id=national_id).exclude(username=username).first()
    existing_by_code = User.objects.filter(employee_code=employee_code).exclude(username=username).first()
    
    if existing_by_national:
        print(f"⚠️  WARNING: National ID {national_id} is already used by user: {existing_by_national.username}")
        print("   This might cause conflicts. Please check the database.")
    
    if existing_by_code:
        print(f"⚠️  WARNING: Employee code {employee_code} is already used by user: {existing_by_code.username}")
        print("   This might cause conflicts. Please check the database.")
    
    if user:
        # Update existing user
        user.is_superuser = True
        user.is_staff = True
        user.is_active = True
        user.set_password(password)
        # Update to secure national_id and employee_code
        user.national_id = national_id
        user.employee_code = employee_code
        user.save()
        print(f"✓ Admin superuser '{username}' updated successfully!")
    else:
        # Create new user - User model requires national_id and employee_code
        user = User.objects.create(
            username=username,
            is_superuser=True,
            is_staff=True,
            is_active=True,
            national_id=national_id,
            employee_code=employee_code,
            role='it_manager',  # Set role to it_manager
        )
        user.set_password(password)
        user.save()
        print(f"✓ Admin superuser '{username}' created successfully!")
    
    # Verify the user
    user.refresh_from_db()
    print(f"\nUser Verification:")
    print(f"  Username: {user.username}")
    print(f"  Is Superuser: {user.is_superuser}")
    print(f"  Is Staff: {user.is_staff}")
    print(f"  Is Active: {user.is_active}")
    password_check = user.check_password(password)
    print(f"  Password Check: {password_check}")
    
    if not password_check:
        print("\n⚠️  WARNING: Password verification failed! Resetting password...")
        user.set_password(password)
        user.save()
        print("✓ Password reset successfully!")
    
    print(f"\nAdmin Panel Access Credentials:")
    print(f"  Username: {username}")
    print(f"  Password: {password}")
    print(f"\n⚠️  Keep these credentials secure!")
    print(f"⚠️  Only this account can access /admin panel.")

if __name__ == '__main__':
    create_admin_superuser()
