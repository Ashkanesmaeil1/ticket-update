# Warehouse Read-Only Access Level - Technical Implementation Documentation

## Executive Summary

**Feature:** Granular Read-Only Warehouse Access Level (Phase 1)  
**Objective:** Implement strictly observational access tier for delegated users  
**Status:** ✅ IMPLEMENTED  
**Date:** 2025-12-24  
**Phase:** Phase 1 - Read-Only Access (View Only)

---

## 1. Architecture Overview

### 1.1 Access Hierarchy

The system implements a three-tier access hierarchy:

```
┌─────────────────────────────────────────┐
│  SUPERVISOR (Owner)                     │
│  - Full ADMIN rights                    │
│  - Write + Manage permissions           │
│  - Can grant/revoke access              │
└─────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│  WRITE DELEGATE                         │
│  - Operational rights                   │
│  - Add/Lend operations                  │
│  - Cannot manage permissions            │
└─────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│  READ DELEGATE (Phase 1)                │
│  - Strictly VIEW only                   │
│  - No state-changing operations         │
│  - Observer interface                   │
└─────────────────────────────────────────┘
```

### 1.2 Permission Resolution Flow

```
User Request
    │
    ▼
get_authorized_warehouse_for_user()
    │
    ├─► Is Supervisor? ──► Return 'supervisor'
    │
    └─► Check WarehouseAccess Table
            │
            ├─► Has 'write' access? ──► Return 'write'
            │
            └─► Has 'read' access? ──► Return 'read'
                    │
                    └─► No access ──► Return None
```

---

## 2. Core Implementation

### 2.1 Permission Resolver Function

**Location:** `dwms/utils.py:274-314`

**Function:** `get_warehouse_access_level(warehouse, user)`

**Returns:**
- `'supervisor'` - Full access (owner)
- `'write'` - Write access (delegated)
- `'read'` - Read-only access (delegated)
- `None` - No access

**Implementation:**
```python
def get_warehouse_access_level(warehouse, user):
    """
    Get user's access level for a warehouse.
    CRITICAL: This function MUST prioritize supervisor ownership over delegation.
    
    Logic Hierarchy:
    1. IF user is supervisor (owner) → 'supervisor' (FULL ACCESS)
    2. ELSE IF user has delegated 'write' access → 'write'
    3. ELSE IF user has delegated 'read' access → 'read'
    4. ELSE → None (no access)
    """
    # PRIORITY 1: Check if supervisor (OWNER-FIRST CHECK)
    is_supervisor_result = _is_supervisor_direct(warehouse, user)
    if is_supervisor_result:
        return 'supervisor'
    
    # PRIORITY 2: Check delegated access (only if NOT supervisor)
    access = WarehouseAccess.objects.get(
        warehouse=warehouse, 
        user=user, 
        is_active=True
    )
    return access.access_level  # 'read' or 'write'
```

### 2.2 Permission Helper Function

**Location:** `dwms/utils.py:332-355`

**Function:** `get_warehouse_permissions(warehouse, user)`

**Purpose:** Provides comprehensive permission flags for template rendering

**Returns Dictionary:**
```python
{
    'access_level': 'supervisor' | 'write' | 'read' | None,
    'can_write': bool,      # True for supervisor or write
    'can_read': bool,        # True for any access level
    'is_supervisor': bool,   # True only for supervisor
    'is_read_only': bool,   # True only for read access
}
```

**Usage:**
```python
permissions = get_warehouse_permissions(warehouse, request.user)
context = {
    'can_write': permissions['can_write'],
    'is_supervisor': permissions['is_supervisor'],
    'is_read_only': permissions['is_read_only'],
    'access_level': permissions['access_level'],
}
```

---

## 3. Backend Security: Operation Locking

### 3.1 Write Access Decorator

**Location:** `dwms/utils.py:357-377`

**Decorator:** `@require_warehouse_write_access`

**Purpose:** Server-side validation to prevent manual URL manipulation

**Implementation:**
```python
@require_warehouse_write_access
def movement_create(request, department_id, item_id=None):
    """Create a stock movement"""
    # Only supervisor or write users can reach this code
    warehouse = get_authorized_warehouse_for_user(department_id, request.user)
    # ... rest of view logic
```

**Behavior:**
- Validates user has write access before view execution
- Blocks read-only users with error message
- Redirects to dashboard if access denied

**Protected Operations:**
- ✅ `location_create` - Create storage location
- ✅ `location_edit` - Edit storage location
- ✅ `item_create` - Create item
- ✅ `item_edit` - Edit item
- ✅ `movement_create` - Create stock movement
- ✅ `lend_create` - Create lend record
- ✅ `lend_return` - Return lend record

### 3.2 Access Validation Flow

```
User Request to Write Operation
    │
    ▼
@require_warehouse_write_access decorator
    │
    ├─► get_authorized_warehouse_for_user()
    │   └─► Returns warehouse or None
    │
    ├─► get_warehouse_access_level()
    │   └─► Returns 'supervisor', 'write', 'read', or None
    │
    └─► Check: access_level in ['supervisor', 'write']?
            │
            ├─► YES ──► Execute view function
            │
            └─► NO ──► Show error message
                    └─► Redirect to dashboard
```

---

## 4. Frontend Implementation: Conditional UI Rendering

### 4.1 Template Variables

All views pass permission flags to templates:

```python
permissions = get_warehouse_permissions(warehouse, request.user)
context = {
    'can_write': permissions['can_write'],
    'is_supervisor': permissions['is_supervisor'],
    'is_read_only': permissions['is_read_only'],
    'access_level': permissions['access_level'],
}
```

### 4.2 Template Conditional Rendering

**Pattern:**
```django
{% if can_write %}
    <!-- Write operation buttons -->
    <a href="{% url 'dwms:movement_create' department.id %}">
        افزودن موجودی
    </a>
{% endif %}
```

**Examples:**

**Dashboard (`templates/dwms/dashboard.html`):**
```django
{% if can_write %}
    <a href="{% url 'dwms:movement_create' department.id %}">
        افزودن موجودی
    </a>
    <a href="{% url 'dwms:lend_create' department.id %}">
        امانت
    </a>
{% endif %}

{% if is_supervisor %}
    <a href="{% url 'dwms:warehouse_access_manage' department.id %}">
        مدیریت دسترسی
    </a>
{% endif %}
```

**Item Detail (`templates/dwms/item_detail.html`):**
```django
{% if can_write %}
    <div class="action-buttons">
        <a href="{% url 'dwms:movement_create_item' ... %}">ورود</a>
        <a href="{% url 'dwms:movement_create_item' ... %}">خروج</a>
        <a href="{% url 'dwms:lend_create_item' ... %}">امانت</a>
        <a href="{% url 'dwms:item_edit' ... %}">ویرایش</a>
    </div>
{% else %}
    <div class="read-only-notice">
        شما فقط اجازه مشاهده این کالا را دارید.
    </div>
{% endif %}
```

**Item List (`templates/dwms/item_list.html`):**
```django
{% if can_write %}
    <a href="{% url 'dwms:movement_create_item' ... %}">
        حرکت
    </a>
{% endif %}

{% if can_write %}
    <a href="{% url 'dwms:item_create' department.id %}" class="fab">
        <i class="fas fa-plus"></i>
    </a>
{% endif %}
```

### 4.3 Read-Only User Experience

**Visible:**
- ✅ View all items
- ✅ View item details
- ✅ View stock levels
- ✅ View movement history
- ✅ View lend records
- ✅ View reports
- ✅ View storage locations

**Hidden:**
- ❌ Create/Edit items
- ❌ Create stock movements
- ❌ Create/Return lends
- ❌ Create/Edit locations
- ❌ Manage access permissions

**User Feedback:**
- Clear messaging: "شما فقط اجازه مشاهده این انبار را دارید"
- No confusing disabled buttons
- Clean observer interface

---

## 5. Queryset Visibility Expansion

### 5.1 Warehouse Selection View

**Location:** `dwms/views.py:35-95`

**Previous Behavior:**
- Only showed warehouses where user is supervisor
- Delegated users couldn't see their warehouses

**Updated Behavior:**
- Shows warehouses where user is supervisor
- Shows warehouses where user has delegated access (read or write)
- Tracks access type for UI display

**Implementation:**
```python
@login_required
def warehouse_selection(request):
    """Entry point - show list of warehouses user can access"""
    user = request.user
    
    # Employees can access warehouses (supervisors OR delegated users)
    if user.role != 'employee':
        return redirect('tickets:dashboard')
    
    warehouses_list = []
    
    # Get supervised warehouses (supervisor access)
    for dept in supervised_depts:
        if dept.has_warehouse:
            warehouse = DepartmentWarehouse.objects.get(department=dept)
            warehouses_list.append({
                'warehouse': warehouse,
                'department': dept,
                'access_type': 'supervisor',
            })
    
    # Get delegated warehouses (read or write access)
    delegated_accesses = WarehouseAccess.objects.filter(
        user=user,
        is_active=True
    ).select_related('warehouse', 'warehouse__department')
    
    for access in delegated_accesses:
        if not any(w['warehouse'].id == access.warehouse.id for w in warehouses_list):
            warehouses_list.append({
                'warehouse': access.warehouse,
                'department': access.warehouse.department,
                'access_type': access.access_level,  # 'read' or 'write'
            })
```

---

## 6. Security Specifications

### 6.1 Defense in Depth

**Layer 1: Database Constraints**
- `WarehouseAccess` model enforces unique user-warehouse pairs
- Foreign key constraints ensure data integrity

**Layer 2: Permission Resolver**
- Centralized permission checking
- Supervisor ownership prioritized over delegation
- Consistent access level determination

**Layer 3: Decorator Protection**
- Server-side validation on all write operations
- Blocks read-only users before view execution
- Prevents manual URL manipulation

**Layer 4: Template Rendering**
- UI hides write operations for read-only users
- Prevents user confusion
- Clean observer interface

### 6.2 Attack Vectors Mitigated

| Attack Vector | Mitigation |
|--------------|------------|
| Manual URL manipulation | `@require_warehouse_write_access` decorator |
| Direct API calls | Server-side validation in views |
| Template injection | Django template escaping |
| Race conditions | Database constraints + atomic operations |

---

## 7. Testing Specifications

### 7.1 Test Cases

#### Test Case 1: Read-Only User Can View Data
**Steps:**
1. Grant user 'read' access to warehouse
2. Login as read-only user
3. Navigate to warehouse dashboard

**Expected:**
- ✅ Dashboard loads
- ✅ All data visible (items, movements, lends)
- ✅ No write operation buttons visible
- ✅ Reports accessible

#### Test Case 2: Read-Only User Cannot Create Items
**Steps:**
1. Login as read-only user
2. Try to access `/dwms/23/items/create/` directly

**Expected:**
- ❌ Access denied
- ✅ Error message: "شما فقط اجازه مشاهده این انبار را دارید"
- ✅ Redirect to dashboard

#### Test Case 3: Read-Only User Cannot Create Movements
**Steps:**
1. Login as read-only user
2. Try to access `/dwms/23/movements/create/` directly

**Expected:**
- ❌ Access denied
- ✅ Error message displayed
- ✅ Redirect to dashboard

#### Test Case 4: Write User Can Perform Operations
**Steps:**
1. Grant user 'write' access to warehouse
2. Login as write user
3. Navigate to warehouse dashboard

**Expected:**
- ✅ Dashboard loads
- ✅ Write operation buttons visible
- ✅ Can create items, movements, lends
- ✅ Cannot manage access permissions

#### Test Case 5: Supervisor Has Full Access
**Steps:**
1. Login as supervisor
2. Navigate to warehouse dashboard

**Expected:**
- ✅ All operations available
- ✅ Access management button visible
- ✅ Can grant/revoke access

### 7.2 Edge Cases

1. ✅ User with no access → Redirected to dashboard
2. ✅ Inactive access record → Treated as no access
3. ✅ Multiple warehouses → All visible in selection
4. ✅ Supervisor + Delegated access → Supervisor takes precedence

---

## 8. Files Modified

### Core Files
1. **`dwms/utils.py`**
   - Added `get_warehouse_permissions()` helper function
   - Updated `require_warehouse_write_access()` decorator

2. **`dwms/views.py`**
   - Updated `warehouse_selection()` to include delegated warehouses
   - Applied `@require_warehouse_write_access` to all write operations:
     - `location_create`
     - `location_edit`
     - `item_create`
     - `item_edit`
     - `movement_create`
     - `lend_create`
     - `lend_return`
   - Updated all views to use `get_warehouse_permissions()`
   - Updated context dictionaries to include permission flags

### Templates (Already Using Conditional Rendering)
- `templates/dwms/dashboard.html` - Uses `can_write` and `is_supervisor`
- `templates/dwms/item_list.html` - Uses `can_write`
- `templates/dwms/item_detail.html` - Uses `can_write`
- Other templates follow same pattern

---

## 9. API Reference

### 9.1 Helper Functions

#### `get_warehouse_access_level(warehouse, user)`
**Returns:** `'supervisor' | 'write' | 'read' | None`

**Usage:**
```python
from dwms.utils import get_warehouse_access_level

access_level = get_warehouse_access_level(warehouse, user)
if access_level == 'read':
    # Read-only user
    pass
```

#### `get_warehouse_permissions(warehouse, user)`
**Returns:** Dictionary with permission flags

**Usage:**
```python
from dwms.utils import get_warehouse_permissions

permissions = get_warehouse_permissions(warehouse, user)
can_write = permissions['can_write']
is_read_only = permissions['is_read_only']
```

#### `@require_warehouse_write_access`
**Usage:**
```python
from dwms.utils import require_warehouse_write_access

@require_warehouse_write_access
def my_write_operation(request, department_id, ...):
    # Only supervisor or write users can reach here
    pass
```

---

## 10. Migration Path

### 10.1 Existing Data

**No migration required** - The system is backward compatible:
- Existing supervisors: Continue to work as before
- Existing write delegates: Continue to work as before
- New read delegates: Can be added via access management

### 10.2 Deployment Steps

1. **Deploy Code Changes**
   - Deploy updated `dwms/utils.py`
   - Deploy updated `dwms/views.py`
   - Templates already support conditional rendering

2. **Grant Read Access**
   - Supervisors can grant 'read' access via access management page
   - System automatically enforces read-only restrictions

3. **Verify Functionality**
   - Test read-only user experience
   - Verify write operations are blocked
   - Confirm UI hides write buttons

---

## 11. Phase 2 Preview: Write Access Calibration

**Status:** Not yet implemented

**Planned Features:**
- Write delegates can perform all operational tasks
- Write delegates cannot manage permissions (supervisor-only)
- Write delegates cannot delete critical records
- Enhanced audit logging for write operations

**Prerequisites:**
- Phase 1 (Read-Only) must be verified and stable
- All read-only restrictions must be working correctly
- No bypass vulnerabilities identified

---

## 12. Success Criteria

✅ **All criteria met:**

1. ✅ Read-only users can view all data
2. ✅ Read-only users cannot perform write operations
3. ✅ Server-side validation blocks manual URL access
4. ✅ UI conditionally renders based on permissions
5. ✅ Warehouse selection includes delegated warehouses
6. ✅ Permission resolver correctly prioritizes supervisor access
7. ✅ All write operations protected by decorator
8. ✅ Clear user feedback for access restrictions
9. ✅ No breaking changes to existing functionality
10. ✅ Backward compatible with existing data

---

## 13. Troubleshooting

### Issue: Read-only user can still see write buttons
**Solution:** Verify template uses `{% if can_write %}` correctly

### Issue: Read-only user can access write URLs
**Solution:** Verify `@require_warehouse_write_access` decorator is applied

### Issue: Warehouse not showing in selection
**Solution:** Verify `WarehouseAccess` record exists with `is_active=True`

### Issue: Permission check returns None
**Solution:** Verify user has either supervisor status or active `WarehouseAccess` record

---

**Document Version:** 1.0  
**Last Updated:** 2025-12-24  
**Author:** Engineering Team  
**Status:** ✅ IMPLEMENTED AND VERIFIED




