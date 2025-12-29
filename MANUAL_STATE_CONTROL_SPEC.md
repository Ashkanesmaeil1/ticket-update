# Manual State Control - Technical Engineering Specification

## Document Purpose

This specification documents the technical requirements for implementing "Manual State Control" in the Ticketing Module. The objective is to decouple the 'Reply' and 'Assign' actions from automated 'Status Update' logic, specifically for the IT Manager's administrative panel.

---

## Executive Summary

**Objective:** Disable automated transition of ticket statuses to "In Progress" (درحال انجام) upon administrative actions such as replying or assigning technicians. All state transitions must be explicitly initiated by the user through a manual status-change interface.

**Current State:** The system employs three automated mechanisms that change ticket status from "open" to "in_progress":
1. Django Signal (pre_save) - Auto-changes on technician assignment
2. View Logic (Reply Handler) - Auto-changes when IT Manager/Technician replies
3. View Logic (Status Update Handler) - Auto-changes when assigning via status update form

**Target State:** All status transitions must be manual-only, with no side effects from reply or assignment operations.

---

## 1. Root Cause Analysis: Trigger-Based Coupling

### 1.1 Current Automated Status Transition Mechanisms

The system currently employs three distinct "Side Effect" mechanisms that automatically update ticket status:

#### A. Django Signal-Based Automation

**Location:** `tickets/models.py`, Lines 644-661

**Mechanism:** `pre_save` signal receiver

**Current Behavior:**
```python
@receiver(pre_save, sender=Ticket)
def auto_change_status_on_technician_assignment(sender, instance, **kwargs):
    """Automatically change ticket status from 'open' to 'in_progress' when assigned to technician"""
    if instance.pk:  # Only for existing tickets
        try:
            old_instance = Ticket.objects.get(pk=instance.pk)
            
            # Check if ticket was just assigned to a technician and status is 'open'
            if (instance.assigned_to and 
                instance.assigned_to.role == 'technician' and 
                instance.status == 'open' and
                (old_instance.assigned_to != instance.assigned_to or old_instance.status != 'open')):
                
                # Auto-change status to 'in_progress'
                instance.status = 'in_progress'
        except Ticket.DoesNotExist:
            pass
```

**Trigger Conditions:**
- Ticket is being saved (pre_save signal)
- `assigned_to` field points to a user with role 'technician'
- Current status is 'open'
- Assignment has changed OR status was not 'open' before

**Impact:** Any save operation that assigns a technician will automatically change status to 'in_progress', even if the assignment was not the primary intent of the operation.

#### B. Reply Handler View Logic

**Location:** `tickets/views.py`, Lines 1491-1494

**Mechanism:** Inline conditional logic within `ticket_detail` view

**Current Behavior:**
```python
# Update ticket status to in_progress only if reply by IT/Tech and current status is open
if user.role in ['it_manager', 'technician'] and ticket.status == 'open':
    ticket.status = 'in_progress'
    ticket.save(update_fields=['status'])
```

**Trigger Conditions:**
- User role is 'it_manager' OR 'technician'
- Ticket current status is 'open'
- Reply is being saved

**Impact:** Any reply from IT Manager or Technician to an "open" ticket will automatically change status to 'in_progress', preventing managers from triaging or commenting without changing state.

#### C. Status Update View Logic

**Location:** `tickets/views.py`, Lines 2174-2180

**Mechanism:** Conditional logic within `update_ticket_status` AJAX view

**Current Behavior:**
```python
# Auto-change status from 'open' to 'in_progress' when IT manager assigns to technician
if (user.role == 'it_manager' and 
    assigned_user.role == 'technician' and 
    original_status == 'open' and
    original_assignment != assigned_user):
    
    ticket.status = 'in_progress'
```

**Trigger Conditions:**
- User role is 'it_manager'
- Assigned user role is 'technician'
- Original status was 'open'
- Assignment is changing to a different user

**Impact:** Even when using the dedicated status update interface, assignment operations automatically override the status field if the ticket was previously "open".

### 1.2 Problem Statement

**Operational Impact:**
- **Triaging Limitations:** IT Managers cannot comment on tickets or assign technicians without prematurely changing ticket status
- **Workflow Interruption:** Status transitions occur as side effects, not explicit user intent
- **State Inconsistency:** Tickets may appear "in progress" even when work hasn't actually begun
- **Audit Trail Ambiguity:** Status changes occur silently, making it difficult to track when work actually started vs. when assignment occurred

**User Experience Issues:**
- Managers lose control over ticket lifecycle management
- Status changes cannot be undone easily (requires manual override)
- Confusion between "assigned" and "in progress" states

---

## 2. Engineering Specifications for Manual Control

### 2.1 Logic Decoupling in Controller (Views/API)

#### A. Reply Logic Refactoring

**File:** `tickets/views.py`

**Location:** `ticket_detail` view, approximately lines 1485-1497

**Required Changes:**

**Remove:**
```python
# Update ticket status to in_progress only if reply by IT/Tech and current status is open
if user.role in ['it_manager', 'technician'] and ticket.status == 'open':
    ticket.status = 'in_progress'
    ticket.save(update_fields=['status'])
```

**Replace With:**
```python
# Status remains unchanged - reply operation is independent of status
# No status modification logic should be present in reply handler
```

**Acceptance Criteria:**
- ✅ Reply save operation appends Reply object to database
- ✅ Ticket.status attribute remains unchanged regardless of reply author role
- ✅ Reply functionality continues to work normally
- ✅ Activity log records "Reply Added" event (separate from status changes)

#### B. Assignment Logic Refactoring

**File:** `tickets/views.py`

**Location 1:** `update_ticket_status` view, approximately lines 2167-2182

**Required Changes:**

**Remove:**
```python
# Auto-change status from 'open' to 'in_progress' when IT manager assigns to technician
if (user.role == 'it_manager' and 
    assigned_user.role == 'technician' and 
    original_status == 'open' and
    original_assignment != assigned_user):
    
    ticket.status = 'in_progress'
```

**Replace With:**
```python
# Assignment is independent of status - only update if explicitly provided
# Status should only change if 'status' parameter is explicitly provided in POST data
```

**Location 2:** Any other assignment operations (verify via codebase search)

**Acceptance Criteria:**
- ✅ Assignment operation updates only `assigned_to` field
- ✅ Status field remains unchanged unless explicitly modified via status parameter
- ✅ Assignment notifications continue to function
- ✅ Activity log records "Technician Assigned" event (separate from status changes)

#### C. Status Update Handler Isolation

**File:** `tickets/views.py`

**Location:** `update_ticket_status` view, approximately lines 2141-2245

**Required Changes:**

**Current Logic Issue:**
The view currently combines assignment and status updates, with automatic status changes as side effects.

**Required Refactoring:**
```python
# Status should ONLY change if explicitly provided in POST data
if status:  # Only if status parameter is explicitly provided
    ticket.status = status
    # Log status change activity

# Assignment should be independent
if assigned_to_id:
    ticket.assigned_to = assigned_user
    # Log assignment activity
    # NO automatic status change
```

**Acceptance Criteria:**
- ✅ Status field only changes when `status` parameter is explicitly provided
- ✅ Assignment field only changes when `assigned_to_id` parameter is explicitly provided
- ✅ Both operations can occur independently
- ✅ Both operations log separate activity events

### 2.2 Removal of Automated Database Signals

**File:** `tickets/models.py`

**Location:** Lines 644-661

**Required Changes:**

**Remove Entire Signal:**
```python
# Signal to automatically change ticket status when assigned to technician
@receiver(pre_save, sender=Ticket)
def auto_change_status_on_technician_assignment(sender, instance, **kwargs):
    """Automatically change ticket status from 'open' to 'in_progress' when assigned to technician"""
    # ... entire function body to be removed
```

**Also Remove Signal Import (if unused elsewhere):**
```python
from django.db.models.signals import pre_save
from django.dispatch import receiver
```

**Verification Steps:**
1. Search codebase for any other uses of `pre_save` signal with Ticket model
2. Verify no other signals depend on this behavior
3. Test that assignment operations no longer trigger status changes

**Acceptance Criteria:**
- ✅ Signal receiver function completely removed
- ✅ No pre_save signals remain that modify Ticket.status
- ✅ Signal imports removed if unused
- ✅ Assignment operations do not trigger status changes

### 2.3 Activity Logging Integrity

**Requirement:** Activity logs must continue to record reply and assignment events, but these must be distinct from status change events.

**Current Implementation:**
The system likely uses activity logging via signals or model save hooks. Verify that:

1. **Reply Activity Logging:**
   - Records: "Reply Added", author, timestamp
   - Does NOT record: Status change (if currently happening)

2. **Assignment Activity Logging:**
   - Records: "Technician Assigned", assigned user, timestamp
   - Does NOT record: Status change (if currently happening)

3. **Status Change Activity Logging:**
   - Records: "Status Changed", old status, new status, user, timestamp
   - Only triggers when status field is explicitly modified

**Files to Verify:**
- `tickets/models.py` (activity logging signals)
- `tickets/signals.py` (if separate signal file exists)
- `tickets/views.py` (manual activity logging)

**Acceptance Criteria:**
- ✅ Reply events logged separately from status changes
- ✅ Assignment events logged separately from status changes
- ✅ Status change events logged only when status explicitly changes
- ✅ Audit trail remains clear and unambiguous

---

## 3. UI/UX Functional Requirements

### 3.1 Independent Status Dropdown

**Requirement:** The status-change interface must be the sole entry point for modifying the ticket's lifecycle phase.

**Current Implementation:** Verify the status update UI component exists and functions independently.

**Location:** Likely in `templates/tickets/ticket_detail.html` or similar template

**Required Behavior:**
- Status dropdown/select must be clearly visible and accessible
- Status change must require explicit user selection
- Status change must be a distinct action from reply/assignment
- Status change form submission must be independent

**UI Components to Verify:**
1. Status dropdown/select element
2. Status update form or AJAX endpoint
3. Status change confirmation (if applicable)
4. Visual indication of current status

**Acceptance Criteria:**
- ✅ Status dropdown is visible and functional
- ✅ Status can be changed independently of other operations
- ✅ Status change requires explicit user action
- ✅ Status change UI is clearly labeled and accessible

### 3.2 Action Confirmation

**Requirement:** When replying, the UI must not include "hidden" checkboxes like "Set to In-Progress on send," ensuring that the state remains static unless the user purposefully navigates to the status menu.

**Files to Verify:**
- `templates/tickets/ticket_detail.html` (reply form)
- `tickets/forms.py` (ReplyForm)

**Required Behavior:**
- Reply form must NOT include status-related fields
- Reply form must NOT include auto-status-change options
- Reply form must be focused solely on message content
- No hidden or implicit status change logic in reply form

**Acceptance Criteria:**
- ✅ Reply form contains only message/content fields
- ✅ No status-related fields in reply form
- ✅ No checkboxes or options for status changes in reply form
- ✅ Reply submission does not trigger status changes

### 3.3 Audit Log Integrity

**Requirement:** The system must continue to log "Reply Added" and "Technician Assigned" events, but these must be distinct from "Status Changed" events in the ticket's history.

**UI Display:** Ticket activity log/history must clearly differentiate between:
- Reply events (messages/comments added)
- Assignment events (technician assigned/reassigned)
- Status change events (status transitions)

**Acceptance Criteria:**
- ✅ Activity log displays reply events separately
- ✅ Activity log displays assignment events separately
- ✅ Activity log displays status change events separately
- ✅ Events are clearly labeled and distinguishable
- ✅ Event timestamps are accurate
- ✅ Event authors are recorded correctly

---

## 4. Implementation Roadmap

### Phase 1: Signal Removal

**Priority:** High

**Steps:**
1. Remove `auto_change_status_on_technician_assignment` signal from `tickets/models.py`
2. Verify signal imports are removed (if unused)
3. Test that assignment operations no longer trigger status changes
4. Verify no other code depends on this signal behavior

**Files Modified:**
- `tickets/models.py`

**Testing:**
- Assign technician to "open" ticket → Status should remain "open"
- Assign technician via different methods → Status should remain unchanged
- Verify no errors in logs related to removed signal

### Phase 2: Reply Handler Refactoring

**Priority:** High

**Steps:**
1. Remove status change logic from `ticket_detail` view reply handler
2. Verify reply save operation works correctly
3. Test that replies from IT Manager/Technician do not change status
4. Verify activity logging for replies still works

**Files Modified:**
- `tickets/views.py` (ticket_detail view)

**Testing:**
- IT Manager replies to "open" ticket → Status should remain "open"
- Technician replies to "open" ticket → Status should remain "open"
- Reply is saved correctly → Database contains reply
- Activity log records reply event

### Phase 3: Assignment Handler Refactoring

**Priority:** High

**Steps:**
1. Remove automatic status change logic from `update_ticket_status` view
2. Refactor to make status and assignment truly independent
3. Ensure status only changes when explicitly provided
4. Test assignment operations independently

**Files Modified:**
- `tickets/views.py` (update_ticket_status view)

**Testing:**
- Assign technician via status update form → Status should remain unchanged (unless explicitly changed)
- Assign technician to "open" ticket → Status should remain "open"
- Change status independently → Status should change correctly
- Change assignment independently → Assignment should change correctly
- Change both together → Both should change correctly

### Phase 4: UI Verification

**Priority:** Medium

**Steps:**
1. Verify status dropdown/form is independent and functional
2. Verify reply form has no status-related fields
3. Verify activity log displays events correctly
4. Test user workflows end-to-end

**Files Verified:**
- `templates/tickets/ticket_detail.html`
- `templates/tickets/ticket_form.html` (if status update UI exists here)
- Activity log templates

**Testing:**
- Status can be changed independently via UI
- Reply form has no status fields
- Activity log shows separate events
- User workflows function as expected

### Phase 5: Regression Testing

**Priority:** Critical

**Steps:**
1. Test all ticket workflows
2. Verify no unintended side effects
3. Verify activity logging integrity
4. Verify notifications still work
5. Test edge cases

**Test Cases:**
- Reply to ticket → Status unchanged
- Assign technician → Status unchanged
- Change status manually → Status changes correctly
- Assign and change status together → Both work correctly
- Multiple replies → Status remains stable
- Reassignment → Status remains stable
- Status changes → Activity log records correctly
- Reply events → Activity log records correctly
- Assignment events → Activity log records correctly

---

## 5. Verification and Acceptance Criteria

### 5.1 Functional Requirements

#### A. Administrative Reply

**Test Case:** IT Manager replies to a "New" (open) ticket

**Expected Behavior:**
- ✅ Reply is saved to database
- ✅ Ticket status remains "New" (open) after page refresh
- ✅ Activity log records "Reply Added" event
- ✅ Activity log does NOT record "Status Changed" event
- ✅ No errors or exceptions occur

#### B. Technician Assignment

**Test Case:** IT Manager assigns a ticket to a specific technician

**Expected Behavior:**
- ✅ Ticket `assigned_to` field is updated
- ✅ Ticket status does NOT automatically change to "In Progress"
- ✅ Ticket status remains in its current state (e.g., "Open" or "New")
- ✅ Activity log records "Technician Assigned" event
- ✅ Activity log does NOT record "Status Changed" event
- ✅ Assignment notifications are sent (if applicable)
- ✅ No errors or exceptions occur

#### C. Manual Status Override

**Test Case:** IT Manager explicitly selects "In Progress" or "Resolved" from the status dropdown

**Expected Behavior:**
- ✅ Ticket status changes to selected value
- ✅ Status change occurs only when explicitly selected
- ✅ Status change does NOT occur as side effect of other operations
- ✅ Activity log records "Status Changed" event with old/new status
- ✅ Status change UI is clearly accessible and functional
- ✅ No errors or exceptions occur

### 5.2 Technical Requirements

#### A. Code Quality

- ✅ No automated status change logic remains in codebase
- ✅ All status changes are explicit and traceable
- ✅ Signal-based automation is completely removed
- ✅ View logic does not contain hidden status change side effects
- ✅ Code follows Django best practices

#### B. Data Integrity

- ✅ Database operations are atomic and consistent
- ✅ Activity logs are accurate and complete
- ✅ No orphaned or inconsistent data states
- ✅ Foreign key relationships remain valid

#### C. Performance

- ✅ No performance degradation from changes
- ✅ Signal removal does not impact performance
- ✅ Status update operations remain efficient
- ✅ Database queries are optimized

### 5.3 User Experience

#### A. UI Clarity

- ✅ Status dropdown/form is clearly visible
- ✅ Status change requires explicit user action
- ✅ Reply form has no confusing status-related fields
- ✅ User can distinguish between assignment and status operations

#### B. Workflow Continuity

- ✅ IT Managers can triage tickets without changing status
- ✅ IT Managers can comment on tickets without changing status
- ✅ IT Managers can assign technicians without changing status
- ✅ Status changes are intentional and controlled
- ✅ All existing workflows continue to function

#### C. Audit Trail

- ✅ Activity log clearly shows reply events
- ✅ Activity log clearly shows assignment events
- ✅ Activity log clearly shows status change events
- ✅ Events are chronologically ordered
- ✅ Event authors and timestamps are accurate

---

## 6. Risk Assessment and Mitigation

### 6.1 Risks

#### A. Breaking Existing Workflows

**Risk:** Removing automated status changes may break workflows that depend on this behavior.

**Mitigation:**
- Document all changes clearly
- Test all ticket workflows thoroughly
- Provide migration guide if needed
- Monitor user feedback after deployment

#### B. Signal Dependencies

**Risk:** Other code may depend on the signal behavior.

**Mitigation:**
- Search codebase for all signal references
- Verify no other code expects automatic status changes
- Test all related functionality
- Review activity logs and notifications

#### C. UI Inconsistency

**Risk:** Users may expect automatic status changes and be confused when they don't occur.

**Mitigation:**
- Update UI to make status change explicit and clear
- Provide user documentation/training
- Ensure status dropdown is prominent and accessible
- Consider user notifications for status changes (if appropriate)

### 6.2 Rollback Plan

If issues arise, rollback steps:

1. **Restore Signal:**
   - Re-add `auto_change_status_on_technician_assignment` signal to `tickets/models.py`
   - Restore signal imports if removed

2. **Restore View Logic:**
   - Re-add status change logic to `ticket_detail` view reply handler
   - Re-add status change logic to `update_ticket_status` view

3. **Verify Functionality:**
   - Test that automated status changes work again
   - Verify no data inconsistencies

**Note:** Rollback should be considered carefully, as it reintroduces the problems this specification aims to solve.

---

## 7. Documentation Requirements

### 7.1 Code Documentation

**Required Updates:**
- Update function docstrings to reflect removal of automatic status changes
- Add comments explaining that status changes are manual-only
- Document explicit status change workflow

### 7.2 User Documentation

**Required Updates:**
- Update user guide to explain manual status change process
- Document that replies and assignments do not change status
- Provide examples of when to change status manually

### 7.3 Technical Documentation

**Required Updates:**
- Update architecture documentation
- Document signal removal
- Document refactored view logic
- Update API documentation (if applicable)

---

## 8. Conclusion

This specification provides a comprehensive plan for implementing Manual State Control in the Ticketing Module. By removing automated status transitions and ensuring all state changes are explicit and user-initiated, the system will provide IT Managers with full control over ticket lifecycle management while maintaining data integrity and audit trail clarity.

**Key Deliverables:**
1. Remove Django signal-based automation
2. Refactor reply handler to remove status change logic
3. Refactor assignment handler to remove status change logic
4. Verify UI components support manual-only status changes
5. Ensure activity logging remains accurate and distinct

**Success Criteria:**
- ✅ Replies do not change ticket status
- ✅ Assignments do not change ticket status
- ✅ Status changes occur only via explicit user action
- ✅ Activity logs remain accurate and distinct
- ✅ All workflows continue to function correctly

---

## Appendix A: Code Locations Reference

### Files to Modify

1. **`tickets/models.py`**
   - Lines 644-661: Remove `auto_change_status_on_technician_assignment` signal

2. **`tickets/views.py`**
   - Lines 1491-1494: Remove status change logic from reply handler
   - Lines 2174-2180: Remove automatic status change from assignment handler
   - Lines 2230-2240: Remove status change message logic (if applicable)

### Files to Verify

1. **`tickets/signals.py`**
   - Verify no other signals modify ticket status

2. **`templates/tickets/ticket_detail.html`**
   - Verify status dropdown/form exists
   - Verify reply form has no status fields

3. **`tickets/forms.py`**
   - Verify ReplyForm has no status fields

4. **Activity Log Templates**
   - Verify events are displayed correctly

---

## Appendix B: Testing Checklist

### Signal Removal
- [ ] Signal function removed from models.py
- [ ] Signal imports removed (if unused)
- [ ] Assignment operations do not trigger status changes
- [ ] No errors in logs related to removed signal

### Reply Handler
- [ ] Status change logic removed from ticket_detail view
- [ ] Replies save correctly
- [ ] Status remains unchanged after reply
- [ ] Activity log records reply events

### Assignment Handler
- [ ] Automatic status change logic removed from update_ticket_status view
- [ ] Assignment operations work correctly
- [ ] Status remains unchanged after assignment
- [ ] Activity log records assignment events

### Status Update Handler
- [ ] Status only changes when explicitly provided
- [ ] Status changes work correctly when explicitly requested
- [ ] Assignment and status changes are independent
- [ ] Activity log records status change events

### UI Verification
- [ ] Status dropdown/form is visible and functional
- [ ] Reply form has no status fields
- [ ] Status can be changed independently
- [ ] Activity log displays events correctly

### End-to-End Testing
- [ ] IT Manager can reply without changing status
- [ ] IT Manager can assign without changing status
- [ ] IT Manager can change status manually
- [ ] All workflows function correctly
- [ ] No regression issues

---

**Document Version:** 1.0  
**Last Updated:** 2024  
**Author:** Technical Architecture Team  
**Status:** Specification Ready for Implementation


