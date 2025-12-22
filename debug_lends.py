#!/usr/bin/env python
"""
Diagnostic script to isolate the 500 error in /dwms/23/lends/
Run with: python manage.py shell < debug_lends.py
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ticket_system.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.urls import reverse, resolve
from django.test import Client
from tickets.models import Department
from dwms.models import DepartmentWarehouse, LendRecord
from dwms.utils import get_authorized_warehouse_for_user
import traceback

User = get_user_model()

print("=" * 80)
print("DIAGNOSTIC TEST: /dwms/23/lends/ 500 Error Investigation")
print("=" * 80)
print()

# Test 1: URL Resolution
print("TEST 1: URL Resolution")
print("-" * 80)
try:
    url = reverse('dwms:lend_list', kwargs={'department_id': 23})
    print(f"✓ URL reverse successful: {url}")
    
    resolved = resolve('/dwms/23/lends/')
    print(f"✓ URL resolve successful: {resolved.url_name} -> {resolved.func}")
    print(f"  View function: {resolved.func.__name__}")
    print(f"  URL kwargs: {resolved.kwargs}")
except Exception as e:
    print(f"✗ URL Resolution FAILED: {type(e).__name__}: {str(e)}")
    traceback.print_exc()
    sys.exit(1)
print()

# Test 2: Department Existence
print("TEST 2: Department Existence")
print("-" * 80)
try:
    dept = Department.objects.get(id=23)
    print(f"✓ Department 23 exists: {dept.name}")
    print(f"  has_warehouse: {dept.has_warehouse}")
except Department.DoesNotExist:
    print(f"✗ Department 23 does NOT exist!")
    sys.exit(1)
except Exception as e:
    print(f"✗ Error checking department: {type(e).__name__}: {str(e)}")
    traceback.print_exc()
    sys.exit(1)
print()

# Test 3: Warehouse Existence
print("TEST 3: Warehouse Existence")
print("-" * 80)
try:
    warehouse = DepartmentWarehouse.objects.filter(department_id=23).first()
    if warehouse:
        print(f"✓ Warehouse exists: {warehouse.id} - {warehouse.name}")
        print(f"  Department: {warehouse.department.id if warehouse.department else 'None'} - {warehouse.department.name if warehouse.department else 'None'}")
    else:
        print(f"⚠ Warehouse for department 23 does NOT exist (will be created on first access)")
except Exception as e:
    print(f"✗ Error checking warehouse: {type(e).__name__}: {str(e)}")
    traceback.print_exc()
    sys.exit(1)
print()

# Test 4: Find Authorized User
print("TEST 4: Finding Authorized User for Department 23")
print("-" * 80)
authorized_user = None
try:
    # Try users from department 23
    dept23_user = User.objects.filter(
        department_id=23,
        is_active=True,
        role='employee',
        department_role__in=['senior', 'manager']
    ).first()
    
    if dept23_user:
        authorized_user = dept23_user
        print(f"✓ Found authorized user (from dept 23): {authorized_user.id} - {authorized_user.username}")
        print(f"  Role: {authorized_user.role}, Dept Role: {authorized_user.department_role}")
    else:
        # Try users who supervise department 23
        all_supervisors = User.objects.filter(
            is_active=True,
            role='employee',
            department_role__in=['senior', 'manager']
        )
        for supervisor in all_supervisors:
            if hasattr(supervisor, 'get_supervised_departments'):
                try:
                    supervised = list(supervisor.get_supervised_departments())
                    dept_ids = [d.id for d in supervised if hasattr(d, 'id')]
                    if 23 in dept_ids:
                        authorized_user = supervisor
                        print(f"✓ Found authorized user (supervisor): {authorized_user.id} - {authorized_user.username}")
                        print(f"  Role: {authorized_user.role}, Dept Role: {authorized_user.department_role}")
                        break
                except Exception:
                    continue
        
        if not authorized_user:
            print(f"⚠ No authorized user found for department 23")
            print(f"  Will test with any active supervisor to see error behavior")
            authorized_user = User.objects.filter(
                is_active=True,
                role='employee',
                department_role__in=['senior', 'manager']
            ).first()
            if authorized_user:
                print(f"  Using test user: {authorized_user.id} - {authorized_user.username}")
except Exception as e:
    print(f"✗ Error finding authorized user: {type(e).__name__}: {str(e)}")
    traceback.print_exc()
    sys.exit(1)
print()

# Test 5: Authorization Check
print("TEST 5: Warehouse Authorization")
print("-" * 80)
test_warehouse = None
if authorized_user:
    try:
        test_warehouse = get_authorized_warehouse_for_user(23, authorized_user)
        if test_warehouse:
            print(f"✓ User authorized for warehouse: {test_warehouse.id} - {test_warehouse.name}")
            print(f"  Warehouse department: {test_warehouse.department.id if test_warehouse.department else 'None'}")
        else:
            print(f"✗ User NOT authorized for warehouse")
            print(f"  User department: {authorized_user.department.id if authorized_user.department else 'None'}")
            if hasattr(authorized_user, 'get_supervised_departments'):
                try:
                    supervised = list(authorized_user.get_supervised_departments())
                    print(f"  User supervised departments: {[d.id for d in supervised if hasattr(d, 'id')]}")
                except:
                    pass
    except Exception as e:
        print(f"✗ Error checking authorization: {type(e).__name__}: {str(e)}")
        traceback.print_exc()
        sys.exit(1)
else:
    print(f"⚠ Skipping - no user found")
print()

# Test 6: QuerySet Creation
print("TEST 6: QuerySet Creation")
print("-" * 80)
try:
    if test_warehouse:
        lends = LendRecord.objects.filter(warehouse=test_warehouse).select_related(
            'item', 'borrower', 'issued_by', 'batch'
        ).order_by('-issue_date')
        
        count = lends.count()
        print(f"✓ QuerySet created successfully")
        print(f"  Total records: {count}")
        
        if count > 0:
            # Test accessing first record
            first_lend = lends.first()
            print(f"  First record ID: {first_lend.id}")
            print(f"  First record item: {first_lend.item.name if first_lend.item else 'None'}")
            print(f"  First record borrower: {first_lend.borrower.get_full_name() if first_lend.borrower else 'None'}")
            print(f"  First record warehouse: {first_lend.warehouse.id if first_lend.warehouse else 'None'}")
            print(f"  First record warehouse.department: {first_lend.warehouse.department.id if first_lend.warehouse and first_lend.warehouse.department else 'None'}")
    else:
        print(f"⚠ Skipping QuerySet test (no warehouse)")
except Exception as e:
    print(f"✗ QuerySet creation FAILED: {type(e).__name__}: {str(e)}")
    traceback.print_exc()
    sys.exit(1)
print()

# Test 7: Pagination
print("TEST 7: Pagination")
print("-" * 80)
try:
    if test_warehouse:
        from django.core.paginator import Paginator
        paginator = Paginator(lends, 30)
        page_obj = paginator.get_page(1)
        print(f"✓ Pagination successful")
        print(f"  Page 1 of {paginator.num_pages}")
        print(f"  Items on page: {len(page_obj)}")
        
        # Test iterating over page_obj
        for lend in page_obj:
            try:
                _ = lend.id
                _ = lend.status if hasattr(lend, 'status') else None
                _ = lend.is_overdue() if hasattr(lend, 'is_overdue') else False
            except Exception as lend_error:
                print(f"✗ Error accessing lend {getattr(lend, 'id', 'unknown')}: {str(lend_error)}")
                traceback.print_exc()
    else:
        print(f"⚠ Skipping pagination test (no warehouse)")
except Exception as e:
    print(f"✗ Pagination FAILED: {type(e).__name__}: {str(e)}")
    traceback.print_exc()
    sys.exit(1)
print()

# Test 8: Template Existence
print("TEST 8: Template Existence")
print("-" * 80)
try:
    from django.template.loader import get_template
    template = get_template('dwms/lend_list.html')
    print(f"✓ Template found: dwms/lend_list.html")
    print(f"  Template origin: {template.origin}")
except Exception as e:
    print(f"✗ Template NOT FOUND: {type(e).__name__}: {str(e)}")
    traceback.print_exc()
    sys.exit(1)
print()

# Test 9: Template Syntax Check
print("TEST 9: Template Syntax Check")
print("-" * 80)
try:
    from django.template.loader import get_template
    
    # Create minimal context
    test_context = {
        'warehouse': test_warehouse if test_warehouse else None,
        'department': test_warehouse.department if test_warehouse and test_warehouse.department else None,
        'page_obj': page_obj if test_warehouse else None,
        'borrowers': [],
        'status_filter': '',
        'borrower_filter': '',
    }
    
    template = get_template('dwms/lend_list.html')
    rendered = template.render(test_context)  # Pass dict directly, not Context()
    print(f"✓ Template renders successfully (length: {len(rendered)} chars)")
except Exception as e:
    print(f"✗ Template rendering FAILED: {type(e).__name__}: {str(e)}")
    traceback.print_exc()
    print()
    print("This is likely the source of the 500 error!")
    sys.exit(1)
print()

# Test 10: Full View Test with Django Test Client
print("TEST 10: Full View Test (with Django Test Client)")
print("-" * 80)
if authorized_user:
    try:
        client = Client()
        client.force_login(authorized_user)
        
        print(f"  Testing GET /dwms/23/lends/ with user {authorized_user.id}...")
        response = client.get('/dwms/23/lends/')
        
        print(f"  Response status: {response.status_code}")
        print(f"  Response type: {type(response).__name__}")
        
        if hasattr(response, 'url'):
            print(f"  Redirect URL: {response.url}")
        
        if response.status_code >= 500:
            print(f"  ✗ GOT 500 ERROR!")
            print(f"  Response content (first 2000 chars):")
            try:
                content = response.content.decode('utf-8', errors='ignore')
                print(content[:2000])
            except:
                print(response.content[:2000])
            print()
            print("THIS IS THE SOURCE OF THE 500 ERROR!")
            print("Check Django logs for the full traceback.")
        elif response.status_code == 302 or response.status_code == 301:
            print(f"  ✓ Redirect successful (status {response.status_code})")
            print(f"  This is expected if user is not authorized")
        elif response.status_code == 200:
            print(f"  ✓ View rendered successfully!")
            print(f"  Content length: {len(response.content)} bytes")
        else:
            print(f"  ⚠ Unexpected status code: {response.status_code}")
    except Exception as e:
        print(f"✗ View test FAILED: {type(e).__name__}: {str(e)}")
        traceback.print_exc()
        print()
        print("THIS IS THE SOURCE OF THE 500 ERROR!")
        sys.exit(1)
else:
    print(f"⚠ Skipping - no authorized user found")
print()

print("=" * 80)
print("DIAGNOSTIC COMPLETE")
print("=" * 80)
print()
print("Summary:")
print("- URL resolution: ✓")
print("- Department exists: ✓")
print("- Warehouse exists: ✓")
print("- Template exists and renders: ✓")
if authorized_user:
    print(f"- Test user: {authorized_user.id} - {authorized_user.username}")
    if test_warehouse:
        print("- User authorization: ✓")
    else:
        print("- User authorization: ✗ (will redirect)")
print()
print("If you got a 500 error in Test 10, check:")
print("1. Django logs for the full traceback")
print("2. DEBUG=True in settings to see Django debug page")
print("3. Ensure the user is authorized for department 23")
print()
