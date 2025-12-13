# Private Reply Feature - Ticketing System

## Overview
The Private Reply feature allows IT Managers to send private messages to employees that are only visible to the intended recipient and authorized personnel.

## Features

### 1. Private Reply Creation
- **IT Managers only** can create private replies
- Private replies are marked with a special badge and visual indicator
- Regular employees and technicians cannot create private replies

### 2. Visibility Rules
- **IT Manager**: Can see all replies including private ones
- **General Manager** (department_role='manager'): Can see all replies including private ones
- **Team Lead** (department_role='senior'): Can see that private replies exist but content is hidden with message "این پیام از شما مخفی شده است"
- **Regular Employee**: Can only see their own private replies and all public replies
- **Technician**: Cannot see private replies (they are filtered out)

### 3. Visual Indicators
- Private replies show a "خصوصی" (Private) badge
- Private content is displayed with a warning alert for authorized users
- Hidden content shows an info alert with explanation for unauthorized users

## Technical Implementation

### Database Changes
- Added `is_private` field to the `Reply` model
- Field is a boolean with default value `False`
- Includes Persian help text and verbose name

### Code Changes
- **Models**: `tickets/models.py` - Added `is_private` field
- **Forms**: `tickets/forms.py` - Updated `ReplyForm` to include private checkbox
- **Views**: `tickets/views.py` - Added permission logic for private replies
- **Services**: `tickets/services.py` - Added filtering functions for reply visibility
- **Templates**: `tickets/ticket_detail.html` - Updated to handle private reply display
- **Admin**: `tickets/admin.py` - Added private field to admin interface

### Permission Functions
- `get_filtered_replies_for_user()`: Filters replies based on user permissions
- `can_view_private_reply_content()`: Checks if user can view private content

## Usage

### For IT Managers
1. Navigate to any ticket detail page
2. In the reply form, check the "پاسخ خصوصی" (Private Reply) checkbox
3. Write your private message
4. Submit the reply

### For Other Users
- Private replies will appear in the reply list with a "خصوصی" badge
- Content visibility follows the permission rules above
- Team leads will see a message indicating the content is hidden

## Installation & Migration

### Using Docker (Recommended)
```bash
# Run the migration script
./run_migration.sh  # Linux/Mac
# OR
run_migration.bat   # Windows

# Or manually with Docker
docker build -t pticket .
docker run --rm -v $(pwd):/app pticket python manage.py migrate
```

### Manual Installation
```bash
# Activate virtual environment
source venv/bin/activate  # Linux/Mac
# OR
venv\Scripts\activate     # Windows

# Run migration
python manage.py migrate
```

## Security Features
- Private replies are only visible to authorized users
- Team leads can see that private replies exist but not their content
- Regular employees cannot create private replies
- All permission checks are enforced at the database and view levels

## Testing
1. Create a ticket as a regular employee
2. Login as IT Manager and add a private reply
3. Login as different user roles to verify visibility rules
4. Check that team leads see the hidden content message

## Future Enhancements
- Private reply notifications
- Audit logging for private reply access
- Bulk private reply operations
- Private reply templates

## Support
For technical support or questions about the Private Reply feature, contact the development team. 