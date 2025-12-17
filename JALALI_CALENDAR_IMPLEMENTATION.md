# Jalali Calendar Deadline Picker - Implementation Guide

## 📋 Overview

This document describes the complete implementation of a sophisticated Jalali (Persian) calendar deadline picker for the Django ticket system. The implementation follows strict architectural constraints where the frontend never directly accesses external APIs.

## 🏗️ Architecture Overview

```
┌─────────────────┐
│   Frontend JS   │
│  (No API Calls) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Django API     │
│  /api/calendar/ │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────┐
│ Service Layer   │◄────►│   SQLite     │
│ calendar_service│      │   Cache      │
└────────┬────────┘      └──────────────┘
         │
         ▼
┌─────────────────┐
│ External API    │
│ pnldev.com/api  │
└─────────────────┘
```

## 📁 File Structure

### Backend Files

1. **`tickets/models.py`**
   - Added `CalendarDay` model to cache calendar data

2. **`tickets/calendar_services/calendar_service.py`**
   - Service layer handling all external API interactions
   - Functions: `fetch_and_cache_month_data()`, `get_or_fetch_month_data()`, `clear_month_cache()`

3. **`tickets/views.py`**
   - Added `calendar_api_view()` - GET endpoint for calendar data

4. **`tickets/urls.py`**
   - Added route: `path('api/calendar/', views.calendar_api_view, name='calendar_api')`

5. **`tickets/forms.py`**
   - Updated `TicketTaskForm.save()` to convert Jalali date/time to Gregorian datetime
   - Date/time fields: `deadline_date` (CharField) and `deadline_time` (TimeField)

### Frontend Files

1. **`static/css/calendar_picker.css`**
   - Modern, responsive styling for calendar modal
   - Holiday highlighting, selection states, animations

2. **`static/js/calendar_picker.js`**
   - `JalaliCalendarPicker` class - main calendar component
   - Handles modal, navigation, day selection, API calls

3. **`templates/tickets/ticket_task_form.html`**
   - Updated to load calendar picker CSS/JS
   - Initializes `JalaliCalendarPicker` on deadline_date input

## 🔄 Data Flow

### 1. Calendar Data Fetching

**User Action**: User clicks on deadline date input field

**Frontend Flow**:
1. `JalaliCalendarPicker` opens modal
2. JavaScript calls: `GET /api/calendar/?year=1403&month=9`
3. Displays loading state

**Backend Flow**:
1. `calendar_api_view()` receives request
2. Calls `get_or_fetch_month_data(year, month)` from service layer
3. Service layer checks `CalendarDay` cache:
   - **Cache Hit**: Returns data from database
   - **Cache Miss**: Calls `fetch_and_cache_month_data()`
     - Makes HTTP request to `https://pnldev.com/api/calender?year=1403&month=9`
     - Parses JSON response
     - Saves/updates `CalendarDay` records in database
     - Returns cached data
4. Returns JSON response to frontend

**Frontend Display**:
1. Renders calendar grid with days
2. Highlights holidays (red background)
3. Shows today indicator (blue border)
4. Makes days clickable

### 2. Date Selection

**User Action**: User clicks on a day

**Frontend Flow**:
1. Day click handler calls `selectDay()`
2. Updates visual selection
3. Calls `showDayDetails()`:
   - Displays Jalali date
   - Shows holiday status if applicable
   - Lists Persian events for that day
4. Enables "Select Deadline" button

**User Action**: User clicks "Select Deadline"

**Frontend Flow**:
1. Reads selected date (Jalali format: `YYYY/MM/DD`)
2. Reads selected time (format: `HH:MM`)
3. Sets input field value to Jalali date
4. Closes modal
5. Time is stored separately in time input field

### 3. Form Submission

**User Action**: User submits task form

**Backend Flow**:
1. `TicketTaskForm.clean()` validates date/time fields
2. `TicketTaskForm.save()` is called:
   - Parses Jalali date string: `"1403/09/24"` → `year=1403, month=9, day=24`
   - Parses time string: `"14:30"` → `hour=14, minute=30`
   - Calls `JalaliCalendarService.jalali_to_gregorian(year, month, day, hour, minute)`
   - Converts to Gregorian datetime with Tehran timezone
   - Saves to `TicketTask.deadline` field (DateTimeField)

**Database Storage**:
- Final deadline is stored as Gregorian datetime in UTC
- Display uses `persian_date` filter to show in Jalali format

## 🔑 Key Features

### 1. Caching System
- All external API data is cached in `CalendarDay` model
- Prevents redundant API calls
- Fast response times after initial fetch
- Cache can be cleared using `clear_month_cache()`

### 2. Holiday Highlighting
- Days with `is_holiday=True` are displayed with red background
- Clear visual distinction from regular days

### 3. Event Display
- Clicking a day shows Persian events (`events_json` field)
- Events are displayed in a clean, readable format

### 4. Modern UX
- Smooth animations and transitions
- Responsive design (mobile-friendly)
- Modal overlay with backdrop
- Keyboard support (ESC to close)
- Loading states during API calls

### 5. Error Handling
- API timeouts and errors are caught gracefully
- User-friendly error messages
- Fallback behavior if API is unavailable

## 🔧 Configuration

### API Endpoint
- External API: `https://pnldev.com/api/calender`
- Internal API: `/api/calendar/`
- Timeout: 10 seconds (configurable in `calendar_service.py`)

### Database Model
- Model: `CalendarDay`
- Unique constraint: `(year, month, day)`
- Indexes on `year`, `month`, and `(year, month)`

## 📝 Migration Required

After implementation, run:

```bash
python manage.py makemigrations tickets
python manage.py migrate tickets
```

This will create the `CalendarDay` table in the database.

## 🚀 Usage Example

```python
# In views.py
from .calendar_services.calendar_service import get_or_fetch_month_data

# Get calendar data (will fetch from API if not cached)
calendar_data = get_or_fetch_month_data(year=1403, month=9)
```

```javascript
// In frontend
const picker = new JalaliCalendarPicker(inputElement, {
    apiUrl: '/api/calendar/',
    onSelect: function(dateStr, timeStr) {
        console.log('Selected:', dateStr, timeStr);
    }
});
```

## ✅ Testing Checklist

- [ ] Calendar modal opens when clicking date input
- [ ] Month navigation works (prev/next buttons)
- [ ] Calendar data loads from API on first access
- [ ] Calendar data loads from cache on subsequent access
- [ ] Holidays are highlighted correctly
- [ ] Day details show on day click
- [ ] Events are displayed correctly
- [ ] Date selection updates input field
- [ ] Time input works independently
- [ ] Form submission converts Jalali to Gregorian correctly
- [ ] Deadline displays correctly in task detail view

## 🔒 Security Considerations

1. **API Rate Limiting**: External API calls should be rate-limited
2. **Input Validation**: Jalali date format is validated before conversion
3. **SQL Injection**: Django ORM prevents SQL injection
4. **XSS Prevention**: Event data is properly escaped in templates

## 📚 Dependencies

- `requests` - For HTTP API calls
- `jdatetime` - For Jalali/Gregorian conversion
- Django 4.2+ (for JSONField support)

## 🎯 Future Enhancements

1. Add cache expiration/TTL for calendar data
2. Implement batch fetching for multiple months
3. Add keyboard navigation in calendar
4. Support for multiple date ranges
5. Export calendar data functionality





