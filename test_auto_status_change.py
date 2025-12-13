#!/usr/bin/env python
"""
Test script for automatic status change when tickets are assigned to technicians.
This script demonstrates the functionality without requiring a full Django test setup.
"""

import os
import sys
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ticket_system.settings')
django.setup()

from tickets.models import User, Ticket
from tickets.forms import TicketStatusForm
from django.test import RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage
from django.utils.translation import gettext_lazy as _

def test_auto_status_change():
    """Test the automatic status change functionality"""
    print("🧪 Testing Automatic Status Change Feature")
    print("=" * 50)
    
    # Find existing users or create new ones with unique codes
    print("1. Finding or creating test users...")
    
    # Find IT Manager
    try:
        it_manager = User.objects.filter(role='it_manager').first()
        if not it_manager:
            # Create IT Manager with unique employee code
            import random
            unique_code = f"IT{random.randint(1000, 9999)}"
            it_manager = User.objects.create(
                username=f'test_it_manager_{unique_code}',
                first_name='مدیر',
                last_name='فناوری',
                email=f'it_manager_{unique_code}@test.com',
                role='it_manager',
                national_id=f'123456789{random.randint(0, 9)}',
                employee_code=unique_code
            )
            it_manager.set_password('testpass123')
            it_manager.save()
            print(f"   ✅ Created IT Manager with code: {unique_code}")
        else:
            print(f"   ℹ️  Using existing IT Manager: {it_manager.get_full_name()}")
    except Exception as e:
        print(f"   ❌ Error with IT Manager: {e}")
        return
    
    # Find Technician
    try:
        technician = User.objects.filter(role='technician').first()
        if not technician:
            # Create Technician with unique employee code
            import random
            unique_code = f"TECH{random.randint(1000, 9999)}"
            technician = User.objects.create(
                username=f'test_technician_{unique_code}',
                first_name='کارشناس فنی',
                last_name='تست',
                email=f'technician_{unique_code}@test.com',
                role='technician',
                national_id=f'098765432{random.randint(0, 9)}',
                employee_code=unique_code
            )
            technician.set_password('testpass123')
            technician.save()
            print(f"   ✅ Created Technician with code: {unique_code}")
        else:
            print(f"   ℹ️  Using existing Technician: {technician.get_full_name()}")
    except Exception as e:
        print(f"   ❌ Error with Technician: {e}")
        return
    
    # Find Employee
    try:
        employee = User.objects.filter(role='employee').first()
        if not employee:
            # Create Employee with unique employee code
            import random
            unique_code = f"EMP{random.randint(1000, 9999)}"
            employee = User.objects.create(
                username=f'test_employee_{unique_code}',
                first_name='کارمند',
                last_name='تست',
                email=f'employee_{unique_code}@test.com',
                role='employee',
                national_id=f'112233445{random.randint(0, 9)}',
                employee_code=unique_code
            )
            employee.set_password('testpass123')
            employee.save()
            print(f"   ✅ Created Employee with code: {unique_code}")
        else:
            print(f"   ℹ️  Using existing Employee: {employee.get_full_name()}")
    except Exception as e:
        print(f"   ❌ Error with Employee: {e}")
        return
    
    # Create test ticket
    print("\n2. Creating test ticket...")
    try:
        ticket = Ticket.objects.create(
            title='تیکت تست برای بررسی تغییر خودکار وضعیت',
            description='این تیکت برای تست تغییر خودکار وضعیت از باز به در حال انجام ایجاد شده است.',
            category='software',
            priority='medium',
            status='open',
            created_by=employee
        )
        print(f"   ✅ Created test ticket (ID: {ticket.id})")
    except Exception as e:
        print(f"   ❌ Error creating ticket: {e}")
        return
    
    print("   📋 Initial ticket status: {}".format(ticket.get_status_display()))
    print("   👤 Assigned to: {}".format(ticket.assigned_to.get_full_name() if ticket.assigned_to else "None"))
    
    # Test automatic status change
    print("\n3. Testing automatic status change...")
    
    # Setup request factory for form testing
    factory = RequestFactory()
    request = factory.post('/fake-url/')
    
    # Add messages framework to request
    setattr(request, 'session', {})
    messages = FallbackStorage(request)
    setattr(request, '_messages', messages)
    
    # Create form data for assignment
    form_data = {
        'status': 'open',  # Keep status as open initially
        'assigned_to': technician.id  # Assign to technician
    }
    
    # Create and test the form
    form = TicketStatusForm(data=form_data, instance=ticket, user=it_manager)
    form.user = it_manager
    form.request = request
    
    if form.is_valid():
        print("   ✅ Form is valid")
        
        # Save the form (this should trigger auto status change)
        updated_ticket = form.save()
        
        print("   📋 New ticket status: {}".format(updated_ticket.get_status_display()))
        print("   👤 New assignment: {}".format(updated_ticket.assigned_to.get_full_name() if updated_ticket.assigned_to else "None"))
        
        # Check if status was automatically changed
        if updated_ticket.status == 'in_progress':
            print("   🎉 SUCCESS: Status automatically changed from 'open' to 'in_progress'!")
        else:
            print("   ❌ FAILED: Status was not automatically changed")
            
    else:
        print("   ❌ Form validation failed:")
        for field, errors in form.errors.items():
            print("      {}: {}".format(field, errors))
    
    # Test reverse scenario (assigning to non-technician)
    print("\n4. Testing assignment to non-technician (should not change status)...")
    
    # Create a new ticket for this test
    try:
        test_ticket2 = Ticket.objects.create(
            title='تیکت تست دوم - بررسی عدم تغییر وضعیت',
            description='این تیکت برای تست عدم تغییر وضعیت هنگام تخصیص به غیر کارشناس فنی ایجاد شده است.',
            category='hardware',
            priority='low',
            status='open',
            created_by=employee
        )
        
        # Assign to IT Manager instead of technician
        form_data2 = {
            'status': 'open',
            'assigned_to': it_manager.id
        }
        
        form2 = TicketStatusForm(data=form_data2, instance=test_ticket2, user=it_manager)
        form2.user = it_manager
        form2.request = request
        
        if form2.is_valid():
            updated_ticket2 = form2.save()
            print("   📋 Status after assigning to IT Manager: {}".format(updated_ticket2.get_status_display()))
            
            if updated_ticket2.status == 'open':
                print("   ✅ CORRECT: Status remained 'open' when assigning to IT Manager")
            else:
                print("   ❌ INCORRECT: Status changed when it shouldn't have")
        else:
            print("   ❌ Form validation failed")
            
    except Exception as e:
        print(f"   ❌ Error in reverse test: {e}")
    
    print("\n" + "=" * 50)
    print("🏁 Test completed!")
    print("\nTo test manually:")
    print("1. Login as IT Manager")
    print("2. Go to ticket detail page for ticket ID: {}".format(ticket.id))
    print("3. Assign the ticket to a technician")
    print("4. Verify the status changes from 'Open' to 'In Progress'")

if __name__ == '__main__':
    test_auto_status_change() 