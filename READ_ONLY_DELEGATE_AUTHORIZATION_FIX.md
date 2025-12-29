# Read-Only Delegate Authorization Bypass Fix - Technical Documentation

## Executive Summary

**Issue:** 403 "Permission Denied" error for read-only delegates when accessing warehouse via "Manage Inventory" button  
**Root Cause:** `warehouse_management` view had strict supervisor-only authorization check  
**Status:** ✅ RESOLVED  
**Date:** 2025-12-24

---

## 1. Root Cause Analysis

### 1.1 The Authorization Bypass Failure

**Problem:** Read-only delegates were receiving "Permission Denied" errors when clicking the "Manage Inventory" (مدیریت انبار) button on the dashboard.

**Error Flow:**
```
User clicks "Manage Inventory" button
    ↓
Redirects to tickets:warehouse_management
    ↓
View checks: if user.department_role not in ['senior', 'manager']
    ↓
Read-only delegate fails check (not supervisor)
    ↓
messages.error() + redirect('tickets:dashboard')
    ↓
"شما اجازه دسترسی به این بخش را ندارید" message
```

### 1.2 Strict Supervisor-Only Authorization

**Previous Logic (Restrictive):**
```python
# ❌ BEFORE - Supervisor only
if user.role != 'employee' or user.department_role not in ['senior', 'manager']:
    messages.error(request, _('شما اجازه دسترسی به این بخش را ندارید.'))
    return redirect('tickets:dashboard')
```

**Impact:**
- Read-only delegates: Blocked with 403 error
- Write delegates: Blocked with 403 error
- Only supervisors could access warehouse management

### 1.3 Dashboard Button Integration

**Location:** `templates/tickets/dashboard.html:1247`

**Button Code:**
```django
<a href="{% url 'tickets:warehouse_management' %}" class="section-action">
    <i class="fas fa-eye"></i>
    {% trans "مدیریت انبار" %}
</a>
```

**Issue:** Button points to `warehouse_management` view which blocks delegates.

---

## 2. Engineering Specifications & Implementation

### 2.1 Unified Permission Model (Union Logic)

**Principle:** User can access warehouse if they are:
1. **Owner (Supervisor)** - Direct ownership via department supervision
2. **OR Delegate** - Has active record in `WarehouseAccess` table (read or write)

**Implementation Pattern:**
```python
# Union permission check
has_access = (
    is_supervisor(user) OR
    has_delegated_access(user)
)
```

### 2.2 View Authorization Refactoring

**File:** `tickets/views.py:4007-4043`  
**Function:** `warehouse_management(request)`

**Updated Logic:**
```python
@login_required
def warehouse_management(request):
    """
    Warehouse management view - accessible to supervisors and delegated users.
    Redirects to the new DWMS system (warehouse_selection) which supports all access levels.
    """
    user = request.user
    
    # Only employees can access warehouses
    if user.role != 'employee':
        messages.error(request, _('شما اجازه دسترسی به این بخش را ندارید.'))
        return redirect('tickets:dashboard')
    
    # UNION 1: Check supervisor access
    has_access = False
    warehouse_departments = []
    
    is_supervisor = user.department_role in ['senior', 'manager']
    if is_supervisor:
        supervised_depts = user.get_supervised_departments()
        warehouse_departments = [d for d in supervised_depts if d.has_warehouse]
        if warehouse_departments:
            has_access = True
    
    # UNION 2: Check delegated access (read or write)
    from dwms.models import WarehouseAccess
    delegated_accesses = WarehouseAccess.objects.filter(
        user=user,
        is_active=True
    ).select_related('warehouse', 'warehouse__department')
    
    if delegated_accesses.exists():
        has_access = True
        # Add delegated warehouses to list
        for access in delegated_accesses:
            dept = access.warehouse.department
            if dept.has_warehouse and dept not in warehouse_departments:
                warehouse_departments.append(dept)
    
    if not has_access:
        messages.error(request, _('شما به هیچ انباری دسترسی ندارید.'))
        return redirect('tickets:dashboard')
    
    # Redirect to new DWMS system which supports all access levels
    return redirect('dwms:warehouse_selection')
```

### 2.3 Key Changes

1. **Removed Supervisor-Only Restriction:**
   - Changed from: `if user.department_role not in ['senior', 'manager']`
   - To: `if user.role != 'employee'` (allows all employees)

2. **Added Union Permission Check:**
   - Checks supervisor access (existing)
   - Checks delegated access via `WarehouseAccess` table (new)
   - Combines both sources

3. **Redirect to DWMS System:**
   - Redirects all users to `dwms:warehouse_selection`
   - DWMS system already supports all access levels
   - Proper permission handling for read/write/supervisor

---

## 3. Sidebar Menu Integration

### 3.1 Persistent Navigation Link

**Location:** `templates/base.html:586-592`

**Template Code:**
```django
{% comment %}DWMS Warehouse link for all users with warehouse access (supervisors, write delegates, read delegates){% endcomment %}
{% if has_warehouse_access %}
    <li class="nav-item">
        <a class="nav-link {% if '/dwms/' in request.path %}active{% endif %}" 
           href="{% url 'dwms:warehouse_selection' %}">
            <i class="fas fa-warehouse me-2"></i>{% trans "انبار بخش" %}
        </a>
    </li>
{% endif %}
```

**Status:** ✅ Already implemented and working

**Behavior:**
- Menu item visible if `has_warehouse_access` is `True`
- Works for supervisors, write delegates, and read delegates
- Active state when on `/dwms/` paths
- Links directly to `dwms:warehouse_selection`

### 3.2 Context Processor

**File:** `tickets/context_processors.py:4-58`  
**Function:** `warehouse_access(request)`

**Status:** ✅ Already updated to include delegated access

**Returns:**
```python
{
    'has_warehouse_access': bool  # True if user has any warehouse access
}
```

---

## 4. Operational Constraint Verification (Read-Only Safety)

### 4.1 Entry Verification

**Test:** Read-only user clicks "Manage Inventory" button

**Expected Flow:**
```
User clicks "Manage Inventory"
    ↓
warehouse_management view
    ↓
Checks delegated access → Found (read access)
    ↓
has_access = True
    ↓
Redirects to dwms:warehouse_selection
    ↓
warehouse_selection view
    ↓
Shows warehouses where user has access
    ↓
User selects warehouse
    ↓
Dashboard loads with read-only permissions
```

**Result:** ✅ No 403 error, successful entry

### 4.2 Observational Access

**Test:** Read-only user can view data

**Expected:**
- ✅ Can see stock list
- ✅ Can see QR scanner (view-only)
- ✅ Can see reports
- ✅ Can view item details
- ✅ Can view movement history
- ✅ Can view lend records

**Result:** ✅ All observational features accessible

### 4.3 Action Lock

**Test:** Read-only user cannot perform write operations

**Expected:**
- ❌ "Add Stock" button hidden
- ❌ "Lend" button hidden
- ❌ "Edit" buttons hidden
- ❌ Write operation URLs blocked (server-side)

**Implementation:**
- Template uses `{% if can_write %}` to hide buttons
- Views use `@require_warehouse_write_access` decorator
- Permission resolver returns `'read'` for read-only users

**Result:** ✅ All write operations properly locked

### 4.4 Sidebar Visibility

**Test:** "Department Warehouse" link appears in navigation

**Expected:**
- ✅ Link visible immediately upon login
- ✅ Link appears in sidebar menu
- ✅ Link is clickable
- ✅ Link shows active state when on warehouse pages

**Result:** ✅ Sidebar integration working correctly

---

## 5. Technical Specifications

### 5.1 Permission Model

**Union Logic:**
```python
def user_has_warehouse_access(user):
    """
    Returns True if user has ANY level of access to any warehouse.
    Uses UNION logic: supervisor OR delegate
    """
    # Check supervisor access
    if is_supervisor(user):
        supervised_depts = get_supervised_departments(user)
        if any(dept.has_warehouse for dept in supervised_depts):
            return True
    
    # Check delegated access
    if WarehouseAccess.objects.filter(user=user, is_active=True).exists():
        return True
    
    return False
```

### 5.2 Access Level Hierarchy

```
SUPERVISOR (Owner)
    │
    ├─► Full access (write + manage)
    └─► Can grant/revoke access
    
WRITE DELEGATE
    │
    ├─► Operational access (write)
    └─► Cannot manage permissions
    
READ DELEGATE
    │
    ├─► View-only access (read)
    └─► No write operations
```

### 5.3 Database Queries

**Warehouse Management Query:**
```python
# Supervisor warehouses
supervised_depts = get_supervised_departments(user)
warehouse_departments = [d for d in supervised_depts if d.has_warehouse]

# Delegated warehouses
delegated_warehouses = WarehouseAccess.objects.filter(
    user=user,
    is_active=True
).select_related('warehouse', 'warehouse__department')
```

**Performance:**
- Uses `select_related()` for efficient queries
- Single query per access type
- Minimal database load

---

## 6. Verification Checklist

### 6.1 Entry Verification

- [x] Read-only user clicks "Manage Inventory" button
- [x] No 403 error occurs
- [x] Successfully enters warehouse selection page
- [x] Can see warehouses where they have access

### 6.2 Observational Access

- [x] Can see stock list
- [x] Can see QR scanner
- [x] Can see reports
- [x] Can view all data (read-only)

### 6.3 Action Lock

- [x] "Add Stock" button hidden
- [x] "Lend" button hidden
- [x] "Edit" buttons hidden
- [x] Write operation URLs blocked (server-side)

### 6.4 Sidebar Visibility

- [x] "Department Warehouse" link appears in navigation
- [x] Link visible immediately upon login
- [x] Link is clickable
- [x] Link shows active state

---

## 7. Files Modified

### 7.1 Core Files

1. **`tickets/views.py`**
   - Updated `warehouse_management()` function
   - Removed supervisor-only restriction
   - Added delegated access check
   - Redirects to DWMS system

2. **`templates/base.html`**
   - Updated comment to reflect all access levels
   - No functional changes (already working)

### 7.2 Related Files (No Changes Required)

1. **`tickets/context_processors.py`**
   - Already updated to include delegated access
   - No changes needed

2. **`dwms/views.py:warehouse_selection()`**
   - Already supports all access levels
   - No changes needed

3. **`dwms/utils.py`**
   - Permission functions already support delegated access
   - No changes needed

---

## 8. Security Considerations

### 8.1 Defense in Depth

**Layer 1: Context Processor**
- Controls menu visibility
- UI-level access control

**Layer 2: View Entry Point**
- Validates user has access before redirecting
- Handles empty lists gracefully

**Layer 3: Permission Resolver**
- Centralized permission checking
- Consistent access level determination

**Layer 4: Write Operation Decorators**
- Server-side validation on all write operations
- Blocks read-only users from write URLs

**Layer 5: Template Rendering**
- Conditionally hides write buttons
- Prevents user confusion

### 8.2 Attack Vectors Mitigated

| Attack Vector | Mitigation |
|--------------|------------|
| Direct URL access | View validates access before redirect |
| Menu manipulation | Server-side validation |
| Permission bypass | Union permission model |
| SQL injection | Django ORM protection |

---

## 9. User Experience Flow

### 9.1 Read-Only User Journey

```
1. User logs in
   ↓
2. Sees "Department Warehouse" in sidebar (persistent link)
   ↓
3. Clicks "Manage Inventory" on dashboard
   ↓
4. warehouse_management view checks access
   ↓
5. Finds delegated access → has_access = True
   ↓
6. Redirects to dwms:warehouse_selection
   ↓
7. warehouse_selection shows accessible warehouses
   ↓
8. User selects warehouse
   ↓
9. Dashboard loads with read-only permissions
   ↓
10. Can view all data, write buttons hidden
```

### 9.2 Write User Journey

```
1. User logs in
   ↓
2. Sees "Department Warehouse" in sidebar
   ↓
3. Clicks "Manage Inventory" on dashboard
   ↓
4. warehouse_management view checks access
   ↓
5. Finds delegated write access → has_access = True
   ↓
6. Redirects to dwms:warehouse_selection
   ↓
7. warehouse_selection shows accessible warehouses
   ↓
8. User selects warehouse
   ↓
9. Dashboard loads with write permissions
   ↓
10. Can view all data, write buttons visible
```

---

## 10. Testing Specifications

### 10.1 Test Cases

#### Test Case 1: Read-Only User Entry
**Steps:**
1. Grant user 'read' access to warehouse
2. Login as read-only user
3. Click "Manage Inventory" button

**Expected:**
- ✅ No 403 error
- ✅ Redirects to warehouse selection
- ✅ Can see warehouse with read access
- ✅ Dashboard loads with read-only permissions

#### Test Case 2: Read-Only User Observational Access
**Steps:**
1. Login as read-only user
2. Navigate to warehouse dashboard
3. Verify data visibility

**Expected:**
- ✅ Stock list visible
- ✅ QR scanner accessible (view-only)
- ✅ Reports accessible
- ✅ All data visible

#### Test Case 3: Read-Only User Action Lock
**Steps:**
1. Login as read-only user
2. Navigate to warehouse dashboard
3. Verify write buttons

**Expected:**
- ❌ "Add Stock" button hidden
- ❌ "Lend" button hidden
- ❌ "Edit" buttons hidden
- ❌ Direct URL access to write operations blocked

#### Test Case 4: Sidebar Visibility
**Steps:**
1. Login as read-only user
2. Check sidebar navigation

**Expected:**
- ✅ "Department Warehouse" link visible
- ✅ Link is clickable
- ✅ Link shows active state on warehouse pages

---

## 11. Troubleshooting

### Issue: Still Getting 403 Error

**Possible Causes:**
1. `WarehouseAccess` record doesn't exist
2. `WarehouseAccess.is_active = False`
3. User role is not 'employee'
4. Cache issue

**Solution:**
1. Verify `WarehouseAccess` record: `WarehouseAccess.objects.filter(user=user, is_active=True)`
2. Check user role: `user.role == 'employee'`
3. Clear browser cache and try again

### Issue: Menu Not Visible

**Possible Causes:**
1. Context processor not registered
2. `has_warehouse_access` returns False
3. Template not using variable

**Solution:**
1. Check context processor registration in `settings.py`
2. Verify `WarehouseAccess` record exists
3. Check template uses `{% if has_warehouse_access %}`

### Issue: Redirect Loop

**Possible Causes:**
1. `warehouse_selection` view also blocking access
2. No warehouses found
3. Permission check failing

**Solution:**
1. Verify `warehouse_selection` allows delegated users (already fixed)
2. Check warehouses exist: `DepartmentWarehouse.objects.filter(...)`
3. Verify permission check logic

---

## 12. Success Criteria

✅ **All criteria met:**

1. ✅ No 403 errors for read-only delegates
2. ✅ Read-only users can access warehouse via "Manage Inventory" button
3. ✅ Read-only users can access warehouse via sidebar link
4. ✅ Observational access works (stock list, QR scanner, reports)
5. ✅ Action lock enforced (write buttons hidden, URLs blocked)
6. ✅ Sidebar link visible immediately upon login
7. ✅ Write users can access warehouse (existing functionality)
8. ✅ Supervisors can access warehouse (existing functionality)
9. ✅ No breaking changes to existing functionality
10. ✅ Backward compatible with existing data

---

## 13. Related Documentation

- **Read-Only Access Implementation:** `WAREHOUSE_READ_ONLY_ACCESS_IMPLEMENTATION.md`
- **Menu Visibility Fix:** `WAREHOUSE_MENU_VISIBILITY_FIX.md`
- **Entry Authorization Fix:** `WAREHOUSE_ENTRY_AUTHORIZATION_FIX.md`
- **Access Management:** `WAREHOUSE_ACCESS_UNIQUE_CONSTRAINT_FIX.md`

---

**Document Version:** 1.0  
**Last Updated:** 2025-12-24  
**Author:** Engineering Team  
**Status:** ✅ IMPLEMENTED AND VERIFIED




