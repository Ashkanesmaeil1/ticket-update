# Django Admin Security Configuration

## Overview
This system implements strict security measures to prevent unauthorized access to the Django admin panel (`/admin`).

## Security Features

### 1. Admin Access Restriction Middleware
- **Location**: `tickets/admin_security.py`
- **Purpose**: Blocks all users except the designated admin superuser from accessing `/admin`
- **Protection**: Even IT managers with superuser privileges cannot access Django admin

### 2. Admin Superuser Account
- **Username**: `iTpArgaSI1rRanTtP`
- **Password**: `Xt2G6xCgGd8voj5`
- **Access**: Only this account can access `/admin` panel
- **Status**: Created and configured

## How It Works

1. **Middleware Check**: When any user tries to access `/admin/*`, the middleware intercepts the request
2. **Username Verification**: Checks if the logged-in user's username matches `iTpArgaSI1rRanTtP`
3. **Access Control**:
   - ✅ **Allowed**: Only the specific admin superuser
   - ❌ **Blocked**: All other users (including IT managers, even if they are superusers)

## Security Benefits

- **Prevents Privilege Escalation**: If an IT manager account is compromised, the attacker cannot access Django admin
- **Separation of Concerns**: IT managers can manage the ticket system, but cannot access Django admin
- **Hardcoded Protection**: The admin username is hardcoded in the middleware, making it difficult to bypass

## Creating/Updating Admin Superuser

To create or update the admin superuser account, run:

```bash
docker-compose exec web python create_admin_superuser.py
```

Or manually:

```bash
docker-compose exec web python manage.py shell
```

Then in the shell:
```python
from django.contrib.auth import get_user_model
User = get_user_model()
user = User.objects.get_or_create(username='iTpArgaSI1rRanTtP')[0]
user.is_superuser = True
user.is_staff = True
user.is_active = True
user.set_password('Xt2G6xCgGd8voj5')
user.save()
```

## Important Notes

⚠️ **Keep the admin credentials secure!**
⚠️ **Do not share the admin username/password with IT managers**
⚠️ **Only use the admin account for Django admin panel access**
⚠️ **IT managers should use their regular accounts for the ticket system**

## Testing

1. Try accessing `/admin` with an IT manager account → Should be blocked (403 Forbidden)
2. Try accessing `/admin` with the admin superuser account → Should work
3. Try accessing `/admin` while logged out → Should redirect to login

## Troubleshooting

If the middleware is not working:
1. Check that `tickets.admin_security.AdminAccessRestrictionMiddleware` is in `MIDDLEWARE` in `settings.py`
2. Verify the middleware is placed after `AuthenticationMiddleware`
3. Restart the Django server after making changes


