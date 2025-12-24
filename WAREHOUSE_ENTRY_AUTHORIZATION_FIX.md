# Warehouse Entry Authorization & Sidebar Integration - Technical Documentation

## Executive Summary

**Issue:** 403 "Permission Denied" error for delegated users when accessing warehouse views  
**Root Cause:** Entry point view needed unified permission model (supervisor OR delegate)  
**Status:** ✅ RESOLVED  
**Date:** 2025-12-24

---

## 1. Root Cause Analysis

### 1.1 The 403 Error

**Problem:** Delegated users (read or write) were receiving "Permission Denied" errors when attempting to access warehouse views.

**Root Cause:** The entry point view (`warehouse_selection`) and related views were using a restrictive permission model that only checked for supervisor status, ignoring delegated access via the `WarehouseAccess` table.

### 1.2 Permission Model Issue

**Previous Logic (Restrictive):**
```python
# ❌ BEFORE - Supervisor only
if user.role != 'employee' or user.department_role not in ['senior', 'manager']:
    return redirect('tickets:dashboard')
```

**Impact:**
- Read-only delegates: Blocked from accessing warehouse
- Write delegates: Blocked from accessing warehouse
- Only supervisors could access warehouse views

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
    is_supervisor(warehouse, user) OR
    has_delegated_access(warehouse, user)
)
```

### 2.2 Entry Point View Fix

**File:** `dwms/views.py:35-98`  
**Function:** `warehouse_selection(request)`

**Updated Logic:**
```python
@login_required
def warehouse_selection(request):
    """Entry point - show list of warehouses user can access"""
    user = request.user
    
    # Employees can access warehouses (supervisors OR delegated users)
    if user.role != 'employee':
        messages.error(request, _('شما اجازه دسترسی به این بخش را ندارید.'))
        return redirect('tickets:dashboard')
    
    warehouses_list = []
    
    # UNION 1: Get warehouses where user is supervisor
    supervised_depts = get_supervised_departments(user)
    for dept in supervised_depts:
        if dept.has_warehouse:
            warehouse = DepartmentWarehouse.objects.get(department=dept)
            warehouses_list.append({
                'warehouse': warehouse,
                'department': dept,
                'access_type': 'supervisor',
            })
    
    # UNION 2: Get warehouses where user has delegated access
    from .models import WarehouseAccess
    delegated_accesses = WarehouseAccess.objects.filter(
        user=user,
        is_active=True
    ).select_related('warehouse', 'warehouse__department')
    
    for access in delegated_accesses:
        # Only add if not already in list (supervisor takes precedence)
        if not any(w['warehouse'].id == access.warehouse.id for w in warehouses_list):
            warehouses_list.append({
                'warehouse': access.warehouse,
                'department': access.warehouse.department,
                'access_type': access.access_level,  # 'read' or 'write'
            })
    
    # Handle edge cases
    if not warehouses_list:
        messages.info(request, _('شما به هیچ انباری دسترسی ندارید.'))
        return redirect('tickets:dashboard')
    
    # If only one warehouse, redirect directly
    if len(warehouses_list) == 1:
        return redirect('dwms:dashboard', department_id=warehouses_list[0]['department'].id)
    
    # Multiple warehouses - show selection page
    return render(request, 'dwms/warehouse_selection.html', {
        'warehouses': warehouses_list,
    })
```

### 2.3 Key Changes

1. **Removed Supervisor-Only Restriction:**
   - Changed from: `if user.department_role not in ['senior', 'manager']`
   - To: `if user.role != 'employee'` (allows all employees)

2. **Added Union Permission Check:**
   - Checks supervisor access (existing)
   - Checks delegated access (new)
   - Combines both sources

3. **Enhanced Error Handling:**
   - Handles empty warehouse list gracefully
   - Provides helpful message to users
   - Redirects appropriately

---

## 3. Sidebar Menu Integration

### 3.1 Context Processor

**File:** `tickets/context_processors.py:4-58`  
**Function:** `warehouse_access(request)`

**Purpose:** Provides `has_warehouse_access` boolean to all templates for sidebar rendering.

**Implementation:**
```python
def warehouse_access(request):
    """
    Returns True if user has ANY level of warehouse access:
    - Supervisor access (owns warehouse)
    - Write access (delegated)
    - Read access (delegated)
    """
    user = request.user
    
    # Only employees can access warehouses
    if user.role != 'employee':
        return {'has_warehouse_access': False}
    
    # Check supervisor access
    if is_supervisor:
        # ... check supervised warehouses ...
        if warehouse_found:
            return {'has_warehouse_access': True}
    
    # Check delegated access (read or write)
    from dwms.models import WarehouseAccess
    delegated_accesses = WarehouseAccess.objects.filter(
        user=user,
        is_active=True
    ).exists()
    
    if delegated_accesses:
        return {'has_warehouse_access': True}
    
    return {'has_warehouse_access': False}
```

### 3.2 Template Integration

**File:** `templates/base.html:586-592`

**Template Code:**
```django
{% comment %}DWMS Warehouse link for all users with access{% endcomment %}
{% if has_warehouse_access %}
    <li class="nav-item">
        <a class="nav-link {% if '/dwms/' in request.path %}active{% endif %}" 
           href="{% url 'dwms:warehouse_selection' %}">
            <i class="fas fa-warehouse me-2"></i>{% trans "انبار بخش" %}
        </a>
    </li>
{% endif %}
```

**Behavior:**
- Menu item visible if `has_warehouse_access` is `True`
- Works for supervisors, write delegates, and read delegates
- Active state when on `/dwms/` paths
- Links to warehouse selection page

### 3.3 Navigation Flow

```
User Login
    │
    ▼
Context Processor: warehouse_access()
    │
    ├─► Is Supervisor? ──► Check supervised warehouses
    │                         │
    │                         └─► Found? ──► has_warehouse_access = True
    │
    └─► Check WarehouseAccess Table
            │
            ├─► Has active access? ──► has_warehouse_access = True
            │
            └─► No access ──► has_warehouse_access = False
                    │
                    └─► Menu item hidden
                            │
                            ▼
                    User clicks menu
                            │
                            ▼
                    warehouse_selection view
                            │
                            ├─► 0 warehouses ──► Show message, redirect
                            ├─► 1 warehouse ──► Auto-redirect to dashboard
                            └─► Multiple ──► Show selection page
```

---

## 4. Operational Constraint Verification (Read-Only Safety)

### 4.1 Permission Enforcement

**Layer 1: View-Level Protection**
- `@require_warehouse_write_access` decorator on all write operations
- Blocks read-only users before view execution
- Prevents manual URL manipulation

**Layer 2: Template-Level Hiding**
- `{% if can_write %}` conditional rendering
- Write buttons hidden for read-only users
- Clean observer interface

**Layer 3: Permission Resolver**
- `get_warehouse_access_level()` returns 'read', 'write', or 'supervisor'
- Consistent permission checking across views
- Supervisor ownership prioritized

### 4.2 Read-Only User Experience

**Visible Operations:**
- ✅ View all items
- ✅ View item details
- ✅ View stock levels
- ✅ View movement history
- ✅ View lend records
- ✅ View reports
- ✅ View storage locations

**Blocked Operations:**
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

## 5. Engineering Execution Steps

### 5.1 Step 1: Refactor Permission Mixin

**Status:** ✅ COMPLETE

**Implementation:**
- Updated `warehouse_selection` view to use union permission model
- Removed supervisor-only restriction
- Added delegated access check

**Code Location:** `dwms/views.py:35-98`

### 5.2 Step 2: Context Processor

**Status:** ✅ COMPLETE

**Implementation:**
- Updated `warehouse_access` context processor
- Checks both supervisor and delegated access
- Returns `has_warehouse_access` boolean

**Code Location:** `tickets/context_processors.py:4-58`

**Registration:** `ticket_system/settings.py:210`

### 5.3 Step 3: URL Redirection

**Status:** ✅ COMPLETE

**Implementation:**
- Warehouse selection handles multiple scenarios:
  - 0 warehouses: Show message, redirect to dashboard
  - 1 warehouse: Auto-redirect to dashboard
  - Multiple warehouses: Show selection page

**Code Location:** `dwms/views.py:90-98`

### 5.4 Step 4: Read-Only Safety

**Status:** ✅ COMPLETE

**Implementation:**
- All write operations protected by `@require_warehouse_write_access`
- Templates conditionally render based on `can_write`
- Permission resolver enforces read-only restrictions

**Code Location:** 
- Decorators: `dwms/utils.py:357-377`
- Templates: `templates/dwms/*.html`

---

## 6. Technical Specifications

### 6.1 Permission Model

**Union Logic:**
```python
def user_has_warehouse_access(user, warehouse):
    """
    Returns True if user has ANY level of access to warehouse.
    Uses UNION logic: supervisor OR delegate
    """
    # Check supervisor access
    if is_supervisor(warehouse, user):
        return True
    
    # Check delegated access
    if has_delegated_access(warehouse, user):
        return True
    
    return False
```

### 6.2 Access Level Hierarchy

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

### 6.3 Database Queries

**Warehouse Selection Query:**
```python
# Supervisor warehouses
supervised_depts = get_supervised_departments(user)
warehouses = DepartmentWarehouse.objects.filter(
    department__in=supervised_depts,
    department__has_warehouse=True
)

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

## 7. Verification Checklist

### 7.1 Entry Point Access

- [x] Read-only user can access `warehouse_selection` view
- [x] Write user can access `warehouse_selection` view
- [x] Supervisor can access `warehouse_selection` view (existing)
- [x] No 403 errors for delegated users

### 7.2 Sidebar Menu Visibility

- [x] Read-only user sees "انبار بخش" menu
- [x] Write user sees "انبار بخش" menu
- [x] Supervisor sees "انبار بخش" menu (existing)
- [x] Menu links to warehouse selection

### 7.3 Warehouse Selection

- [x] Shows warehouses where user has access
- [x] Displays access type (supervisor/read/write)
- [x] Auto-redirects if single warehouse
- [x] Shows selection page if multiple warehouses
- [x] Handles empty list gracefully

### 7.4 Read-Only Safety

- [x] Read-only user cannot access write URLs
- [x] Write buttons hidden for read-only users
- [x] Server-side validation blocks write operations
- [x] Clear messaging about read-only access

---

## 8. Files Modified

### 8.1 Core Files

1. **`dwms/views.py`**
   - Updated `warehouse_selection()` to use union permission model
   - Added empty warehouse list handling
   - Removed supervisor-only restriction

2. **`tickets/context_processors.py`**
   - Updated `warehouse_access()` to check delegated access
   - Removed supervisor-only restriction
   - Returns `has_warehouse_access` for all access levels

### 8.2 Related Files (No Changes Required)

1. **`templates/base.html`**
   - Already uses `has_warehouse_access` correctly
   - No changes needed

2. **`dwms/utils.py`**
   - Permission functions already support delegated access
   - No changes needed

---

## 9. Security Considerations

### 9.1 Defense in Depth

**Layer 1: Context Processor**
- Controls menu visibility
- UI-level access control

**Layer 2: View Entry Point**
- Validates user has access before showing warehouses
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

### 9.2 Attack Vectors Mitigated

| Attack Vector | Mitigation |
|--------------|------------|
| Direct URL access | View decorators block access |
| Menu manipulation | Server-side validation |
| Permission bypass | Union permission model |
| SQL injection | Django ORM protection |

---

## 10. Performance Considerations

### 10.1 Query Optimization

**Warehouse Selection:**
- Uses `select_related()` for efficient joins
- Single query per access type
- Minimal database load

**Context Processor:**
- Uses `.exists()` for efficient check
- Doesn't load full records
- Cached per request

### 10.2 Caching Opportunities

**Future Enhancement:**
- Cache `has_warehouse_access` per user session
- Cache warehouse list per user
- Invalidate cache when access is granted/revoked

---

## 11. Troubleshooting

### Issue: 403 Error Still Occurring

**Possible Causes:**
1. `WarehouseAccess` record doesn't exist
2. `WarehouseAccess.is_active = False`
3. User role is not 'employee'
4. Warehouse doesn't exist

**Solution:**
1. Verify `WarehouseAccess` record: `WarehouseAccess.objects.filter(user=user, is_active=True)`
2. Check user role: `user.role == 'employee'`
3. Verify warehouse exists: `DepartmentWarehouse.objects.filter(department=dept)`

### Issue: Menu Not Visible

**Possible Causes:**
1. Context processor not registered
2. `has_warehouse_access` returns False
3. Template not using variable

**Solution:**
1. Check context processor registration in `settings.py`
2. Verify `WarehouseAccess` record exists
3. Check template uses `{% if has_warehouse_access %}`

### Issue: Empty Warehouse List

**Possible Causes:**
1. No supervised departments with warehouse
2. No delegated access records
3. All warehouses inactive

**Solution:**
1. Verify supervised departments: `user.get_supervised_departments()`
2. Check delegated access: `WarehouseAccess.objects.filter(user=user, is_active=True)`
3. Verify warehouses exist: `DepartmentWarehouse.objects.all()`

---

## 12. Success Criteria

✅ **All criteria met:**

1. ✅ No 403 errors for delegated users
2. ✅ Read-only users can access warehouse views
3. ✅ Write users can access warehouse views
4. ✅ Supervisors can access warehouse views (existing)
5. ✅ Sidebar menu visible for all access levels
6. ✅ Warehouse selection shows all accessible warehouses
7. ✅ Auto-redirect works for single warehouse
8. ✅ Selection page works for multiple warehouses
9. ✅ Empty list handled gracefully
10. ✅ Read-only restrictions enforced

---

## 13. Related Documentation

- **Read-Only Access Implementation:** `WAREHOUSE_READ_ONLY_ACCESS_IMPLEMENTATION.md`
- **Menu Visibility Fix:** `WAREHOUSE_MENU_VISIBILITY_FIX.md`
- **Access Management:** `WAREHOUSE_ACCESS_UNIQUE_CONSTRAINT_FIX.md`

---

**Document Version:** 1.0  
**Last Updated:** 2025-12-24  
**Author:** Engineering Team  
**Status:** ✅ IMPLEMENTED AND VERIFIED

