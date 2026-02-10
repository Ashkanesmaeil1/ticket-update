# Identifier Synchronization & RBAC Analysis

## Problem Statement

After updating National ID or Personnel Code (Employee Code) in the Administrator Panel, login can still fail. The cause is not only data format (Persian vs English digits) but **Database Synchronization or Role-Based Access Control (RBAC)** failure.

## Technical Root Cause Analysis

### 1. Identifier Desynchronization

- The app uses a **single** `User` model (no separate `UserProfile`). `User` has both `national_id` and `username`.
- **Main app login** uses `NationalIDEmployeeCodeBackend`, which authenticates by `national_id` + `employee_code` (both on `User`). It does **not** use `username`.
- **Admin panel login** uses `AdminModelBackend`, which authenticates by `username` + password.
- Django’s `USERNAME_FIELD` is `national_id`, so `get_username()` returns `national_id`. Many places (admin list, search, display) still use the `username` field.
- **Gap**: When an admin changed `national_id` in the Admin form, `User.username` was **not** updated. So:
  - Main login (national_id + employee_code) could work if the form saved `national_id` correctly.
  - Admin login (username + password) and any code using `username` still saw the **old** value → perceived “login fails” or wrong identity.

### 2. Normalization vs Locale

- In a Dockerized environment, the Admin panel can use a different locale/encoding than the web container. Input may contain Persian/Arabic digits or extra spaces.
- If normalization (Persian/Arabic → English, strip) was not applied **consistently** in the admin form and in the auth backends, the same logical identifier could be stored or queried in different forms → no match at login.

### 3. “Active State” and Unique Constraints

- The code does **not** toggle `is_active` or force password change when identifiers are edited; that was not the cause.
- Unique constraint on `national_id` / `employee_code` can cause save to fail if the new value already exists; the form and model validation handle uniqueness.

## Engineering Specification (Implemented)

### 1. Forced Identity Synchronization

- **Requirement**: Whenever the Administrator panel (or any code path) saves a `User`, the system must keep **username** in sync with **national_id** (the login identifier).
- **Implementation**:
  - In `User.save()` (in `tickets/models.py`), after normalizing `national_id` and `employee_code`, set `self.username = self.national_id` when `national_id` is set and different from current `username`.
  - So after any save (admin edit, API, management command), `username` and `national_id` are identical. Admin login and any use of `username` then see the same value as the one used for main login.

### 2. Normalization Guard (Admin Form)

- **Requirement**: The admin form must strictly convert Persian/Arabic digits to English and strip whitespace before committing, so the login query (which uses normalized values) finds the match.
- **Implementation**:
  - In `CustomUserCreationForm.clean()` (in `tickets/admin.py`), for `national_id` and `employee_code`: strip raw value, then pass to `normalize_national_id` / `normalize_employee_code`. This is documented as the “Normalization Guard” for Docker/locale.

### 3. Authentication Backend Audit

- **Requirement**: Login must not fail due to hidden spaces or Persian/Arabic digits; lookup must use normalized, trimmed values.
- **Implementation**:
  - **NationalIDEmployeeCodeBackend**: Strip `national_id` and `employee_code` before normalizing; then query with normalized values (unchanged behavior, more robust input).
  - **AdminModelBackend**: Strip and normalize the provided `username` with `normalize_national_id()`. Look up by `username=normalized_username`, then fallback to `national_id=normalized_username`, then fallback to raw `username` / `national_id` for legacy data. So admin login works with national_id (including Persian digits and spaces).

## Execution Roadmap (Docker)

1. **Inspect the “real” username**
   - Run:  
     `docker compose exec web python manage.py shell`  
     Then:  
     `from django.contrib.auth import get_user_model; User = get_user_model(); u = User.objects.get(email='user@example.com'); print(u.username, u.national_id)`  
   - Or:  
     `docker compose exec web python manage.py inspect_user_identifiers --user-id <id>`  
   - Confirm that `username` equals `national_id` after an admin edit (identity parity).

2. **Clear identity cache**
   - If using Redis/Memcached for sessions:  
     `docker compose restart redis`  
   - Existing sessions are also invalidated when National ID or Employee Code change (see `tickets/signals.py`).

3. **Trace login failure**
   - During a failed login:  
     `docker compose logs -f web`  
   - Check logs for authentication attempts and “User not found” / “Employee Code mismatch” messages from `NationalIDEmployeeCodeBackend` and `log_authentication_attempt`.

## Acceptance Criteria

| Criterion | Status |
|-----------|--------|
| **Identity parity**: Changing National ID in the Admin Panel updates the username used for login (and for AdminModelBackend). | ✅ Implemented in `User.save()` |
| **Zero-conflict update**: No automatic locking (`is_active=False`) or password reset when only identifiers are changed. | ✅ Not introduced |
| **Log consistency**: Web container logs show authentication attempts with normalized identifiers; inspect command shows username vs national_id. | ✅ Logging and `inspect_user_identifiers` updated |

## Files Changed

- `tickets/models.py`: In `User.save()`, sync `username = national_id` after normalization.
- `tickets/admin.py`: In `CustomUserCreationForm.clean()`, strip then normalize `national_id` and `employee_code` (Normalization Guard).
- `tickets/backends.py`: Strip and normalize in both backends; AdminModelBackend lookup by normalized username and national_id with fallbacks.
- `tickets/management/commands/inspect_user_identifiers.py`: Doc and output extended to show identity parity (username vs national_id).

## Syncing Existing Data

For users already in the DB with `username != national_id`, run a one-off sync (e.g. in shell or a management command):

```python
from tickets.models import User
for u in User.objects.exclude(national_id=None):
    if u.username != u.national_id:
        u.username = u.national_id
        u.save(update_fields=['username'])
```

Or use the existing `normalize_user_identifiers` management command if it updates and saves users; after this implementation, any save will also sync `username` to `national_id`.
