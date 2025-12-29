# System-Wide Numerical Localization for Operational Modules
## Technical Engineering Specification

### Document Purpose
This document outlines the implementation of comprehensive numerical localization across all core inventory and reporting modules (Warehouse, Lending, Movements, and Reports). The update ensures that stock levels, transaction volumes, lending quantities, and statistical reports are rendered using Persian numerical glyphs (۰-۹) to provide a seamless, native experience for administrative and departmental users.

---

## 1. Module-Specific Localization Requirements

### 1.1 Warehouse and Inventory (انبار)

The primary inventory view serves as the source of truth for stock levels. Numerical data in this module must be localized to maintain visual consistency with the rest of the Persian interface.

#### Current Stock Levels
**Location:** `templates/dwms/item_list.html`, `templates/dwms/item_detail.html`
- **All quantities** displayed in the main inventory grid must be converted to Persian digits
- **Format:** `{{ total_stock|floatformat:0|persian_digits }}`
- **Example:** `150` → `۱۵۰`

**Template Updates Required:**
- `item_list.html`: Line 205 - `{{ item_data.total_stock|floatformat:0 }}`
- `item_detail.html`: Line 151 - `{{ total_stock|floatformat:0 }}`
- `item_detail.html`: Line 202 - `{{ stock.total }}`

#### Minimum Threshold Indicators
**Location:** `templates/dwms/item_detail.html`, `templates/dwms/dashboard.html`
- Low-stock alerts and threshold numbers must be localized to ensure immediate readability during audits
- **Format:** `{{ threshold|floatformat:0|persian_digits }}`
- **Example:** `25` → `۲۵`

**Template Updates Required:**
- `item_detail.html`: Line 157 - `{{ item.min_stock_threshold|floatformat:0 }}`
- `dashboard.html`: Line 230 - `{{ low_stock_count|floatformat:0 }}`
- `dashboard.html`: Line 252 - `{{ alert.current_stock|floatformat:0 }}` and `{{ alert.threshold|floatformat:0 }}`

#### Asset Specifications
**Location:** Various templates
- Technical dimensions or measurements associated with specific IT hardware must also reflect the localized digit set
- **Note:** If specifications are stored as text fields, apply `persian_digits` filter during display

#### Dashboard Statistics
**Location:** `templates/dwms/dashboard.html`
- **Total Items:** Line 226 - `{{ total_items }}`
- **Low Stock Count:** Line 230 - `{{ low_stock_count|floatformat:0 }}`
- **Open Lends:** Line 234 - `{{ open_lends|length }}`
- **Recent Movements:** Line 238 - `{{ recent_movements|length }}`

### 1.2 Lending and Loan Management (امانت)

The Lending module tracks the temporary transfer of assets to personnel. Clarity in these numbers is essential for accountability.

#### Quantity Lent
**Location:** `templates/dwms/lend_list.html`, `templates/dwms/lend_return.html`, `templates/dwms/item_detail.html`
- The number of items assigned to an individual must be rendered in Persian digits
- **Format:** `{{ lend.quantity|floatformat:0|persian_digits }}`
- **Example:** `5` → `۵`

**Template Updates Required:**
- `lend_list.html`: Line 236 - `{{ lend.quantity|floatformat:0 }}`
- `lend_return.html`: Line 141 - `{{ lend_record.quantity|floatformat:0 }}`
- `lend_form.html`: Line 143 - `{{ item.get_total_stock|floatformat:0 }}` (stock availability)

#### Return Deadlines
**Location:** `templates/dwms/lend_list.html`, `templates/dwms/lend_return.html`
- Dates and day-counts remaining for lent items must be fully localized
- **Status:** Already using `persian_date` filter ✅
- **Note:** If day-count calculations are added, apply `persian_digits` filter

#### Personnel Counts
**Location:** `templates/dwms/dashboard.html`
- Summaries showing how many items a specific person currently holds must match the dashboard's localization style
- **Status:** Currently using `|length` filter (returns integer) - needs `persian_digits` ✅

**Template Updates Required:**
- `dashboard.html`: Line 234 - `{{ open_lends|length|persian_digits }}`

### 1.3 Stock Movements and Transactions (حرکات)

The Movement log tracks every "Stock-In" and "Stock-Out" event. This is a high-traffic data area.

#### Transaction Volumes
**Location:** `templates/dwms/movement_history.html`, `templates/dwms/item_detail.html`, `templates/dwms/dashboard.html`
- The number of units moved in a single transaction must be localized
- **Format:** `{{ movement.quantity|floatformat:0|persian_digits }}`
- **Example:** `100` → `۱۰۰`

**Template Updates Required:**
- `movement_history.html`: Line 154 - `{{ movement.quantity|floatformat:0 }}`
- `item_detail.html`: Line 220 - `{{ movement.quantity|floatformat:0 }}`
- `dashboard.html`: Line 278 - `{{ movement.quantity|floatformat:0 }}`

#### Movement IDs
**Location:** Currently not displayed (internal reference)
- If movement IDs are displayed in future updates, apply `persian_id` filter
- **Note:** Similar to ticket IDs, use `{{ movement.id|persian_id }}`

#### Sequence Logs
**Location:** Pagination and sequence numbers
- Chronological order numbers in pagination must be localized
- **Status:** Pagination uses Django's built-in paginator (may need custom template tag for page numbers)

### 1.4 System Reports and Analytics (گزارشات)

Reports often aggregate large volumes of data. The localization logic must handle complex numerical strings without degrading performance.

#### Aggregate Totals
**Location:** `templates/dwms/reports_daily.html`
- Summary rows at the bottom of report tables showing total assets or total movements
- **Status:** Partially implemented ✅ (lines 197, 203, 233, 256, 257, 279 already use `persian_digits`)
- **Additional Updates Required:**
  - `reports_daily.html`: Line 215 - `{{ new_lends|length|persian_digits }}` (already applied ✅)

#### Date Range Filters
**Location:** `templates/dwms/reports_daily.html`, `templates/dwms/reports_weekly.html`, `templates/dwms/reports_monthly.html`
- Numbers within the date-picker and the selected range display
- **Status:** Dates already use `persian_date` filter which converts digits to Persian ✅

#### Statistical Summaries
**Location:** `templates/dwms/reports_daily.html`
- Percentage changes or growth indicators within the reporting dashboard
- **Status:** Already using `persian_digits` filter for summary values ✅

#### Location Statistics
**Location:** `templates/dwms/location_list.html`
- Item counts and total inventory per location
- **Template Updates Required:**
  - `location_list.html`: Line 139 - `{{ location.item_count|persian_digits }}`
  - `location_list.html`: Line 140 - `{{ location.total_items|floatformat:0|persian_digits }}`

---

## 2. Architectural Implementation Strategy

### 2.1 Presentation Layer Execution

**Critical Rule:** Localization must be performed at the final stage of the rendering pipeline. This ensures that:
- Backend continues to use standard integers for mathematical operations (`sum()`, `average()`, etc.)
- Database queries remain optimized (no string conversions)
- Aggregation functions work correctly
- Form submissions use standard integer format

**Implementation Pattern:**
```django
{# ✅ Correct: Apply filter at display time #}
{{ total_stock|floatformat:0|persian_digits }}

{# ❌ Incorrect: Converting in view/context #}
# Don't convert in Python before passing to template
```

### 2.2 String Replacement Filter

A global utility function (`persian_digits`) is utilized to intercept numerical strings and map them to the Persian Unicode block.

**Filter Location:** `tickets/templatetags/persian_numbers.py`

**Filter Usage:**
```django
{% load persian_numbers %}

{# Integer values #}
{{ quantity|persian_digits }}

{# Float values with formatting #}
{{ total_stock|floatformat:0|persian_digits }}

{# With default values #}
{{ count|default:0|persian_digits }}

{# Length filters #}
{{ items|length|persian_digits }}
```

**Filter Features:**
- Handles integers, floats, and strings
- Preserves thousands separators (converts to Persian comma: ٬)
- Maintains zero values correctly
- Handles negative numbers
- Returns empty string for `None` values

### 2.3 Preservation of Delimiters

The logic intelligently handles decimal points and thousands-separators, ensuring that Persian punctuation is used in place of Western commas and periods where appropriate.

**Examples:**
- `1,500` → `۱٬۵۰۰` (Persian comma for thousands separator)
- `125.5` → `۱۲۵.۵` (Decimal point preserved, digits converted)
- `1000` → `۱۰۰۰` (No separator needed for 4-digit numbers)

**Current Implementation:**
- The `persian_digits` filter includes thousands separator logic
- Decimal points are preserved (`.`) while digits are converted
- No additional delimiter handling required

---

## 3. Data Integrity and Searchability Guardrails

### 3.1 Search Agnosticism

**Requirement:** The system must remain capable of processing both Persian and Latin digit inputs in search bars.

**Implementation Status:**
- ✅ Ticket search already implements normalization (see `IDENTIFIER_LOCALIZATION_SPEC.md`)
- ⚠️ DWMS search functionality needs verification

**Normalization Middleware Pattern:**
```python
from tickets.templatetags.persian_numbers import _persian_to_latin

if search_query:
    # Normalize Persian digits to Latin for search compatibility
    normalized_query = _persian_to_latin(search_query)
    # Use normalized_query for database queries
```

**Search Functions to Verify:**
- `dwms/views.py`: `item_list` view (if search functionality exists)
- `dwms/views.py`: `movement_history` view (if search functionality exists)
- `dwms/views.py`: `lend_list` view (if search functionality exists)

**Action Required:**
- Verify search functionality in DWMS views
- Apply normalization middleware if search exists
- Document search behavior in testing checklist

### 3.2 Export Consistency

**Requirement:** When a user generates an Excel or PDF report from the "Reports" module, the system must provide an option to either maintain the localized Persian digits (for printing) or revert to Latin digits (for data analysis in external software).

**Implementation Strategy:**
1. **Default Behavior:** Reports display Persian digits in HTML views (current behavior)
2. **Export Options:** Add export format selector (Persian/Latin) to report views
3. **Implementation:**
   - Add query parameter: `?export_format=persian` or `?export_format=latin`
   - In view logic, conditionally apply `persian_digits` filter based on export format
   - For Excel/PDF exports, use raw integer values if `export_format=latin`

**Future Enhancement:**
- Add export format selector UI to report pages
- Implement conditional filter application in report templates
- Document export format behavior

**Current Status:**
- HTML reports use Persian digits ✅
- Excel/PDF export functionality needs to be implemented or verified

---

## 4. Implementation Checklist

### 4.1 Warehouse Module (انبار)

- [ ] **item_list.html**
  - [ ] Line 205: `{{ item_data.total_stock|floatformat:0|persian_digits }}`
  
- [ ] **item_detail.html**
  - [ ] Line 151: `{{ total_stock|floatformat:0|persian_digits }}`
  - [ ] Line 157: `{{ item.min_stock_threshold|floatformat:0|persian_digits }}`
  - [ ] Line 202: `{{ stock.total|persian_digits }}`
  - [ ] Line 220: `{{ movement.quantity|floatformat:0|persian_digits }}`

- [ ] **dashboard.html**
  - [ ] Line 226: `{{ total_items|persian_digits }}`
  - [ ] Line 230: `{{ low_stock_count|floatformat:0|persian_digits }}`
  - [ ] Line 234: `{{ open_lends|length|persian_digits }}`
  - [ ] Line 238: `{{ recent_movements|length|persian_digits }}`
  - [ ] Line 252: `{{ alert.current_stock|floatformat:0|persian_digits }}`
  - [ ] Line 252: `{{ alert.threshold|floatformat:0|persian_digits }}`
  - [ ] Line 278: `{{ movement.quantity|floatformat:0|persian_digits }}`

- [ ] **location_list.html**
  - [ ] Line 139: `{{ location.item_count|persian_digits }}`
  - [ ] Line 140: `{{ location.total_items|floatformat:0|persian_digits }}`

- [ ] **lend_form.html**
  - [ ] Line 143: `{{ item.get_total_stock|floatformat:0|persian_digits }}` (stock availability display)

### 4.2 Lending Module (امانت)

- [ ] **lend_list.html**
  - [ ] Line 236: `{{ lend.quantity|floatformat:0|persian_digits }}`

- [ ] **lend_return.html**
  - [ ] Line 141: `{{ lend_record.quantity|floatformat:0|persian_digits }}`

### 4.3 Movements Module (حرکات)

- [ ] **movement_history.html**
  - [ ] Line 154: `{{ movement.quantity|floatformat:0|persian_digits }}`

### 4.4 Reports Module (گزارشات)

- [x] **reports_daily.html** (Already implemented ✅)
  - [x] Line 197: `{{ total_in|floatformat:0|default:"0"|persian_digits }}`
  - [x] Line 203: `{{ total_out|floatformat:0|default:"0"|persian_digits }}`
  - [x] Line 215: `{{ new_lends|length|persian_digits }}`
  - [x] Line 233: `{{ summary.total|floatformat:0|persian_digits }}`
  - [x] Line 256: `{{ item.get_total_stock|floatformat:0|persian_digits }}`
  - [x] Line 257: `{{ item.min_stock_threshold|floatformat:0|persian_digits }}`
  - [x] Line 279: `{{ lend.quantity|floatformat:0|persian_digits }}`

- [ ] **reports_weekly.html** (Verify and apply if needed)
- [ ] **reports_monthly.html** (Verify and apply if needed)

### 4.5 Template Filter Loading

Ensure all DWMS templates load the `persian_numbers` template tag library:

```django
{% load persian_numbers %}
```

**Templates Requiring Filter Loading:**
- [ ] `item_list.html`
- [ ] `item_detail.html`
- [ ] `dashboard.html`
- [ ] `lend_list.html`
- [ ] `lend_return.html`
- [ ] `movement_history.html`
- [ ] `location_list.html`
- [ ] `lend_form.html` (if stock display is added)

---

## 5. Verification and Acceptance Criteria

### 5.1 Module Audit

**Requirement:** Every numerical value in the Warehouse, Lending, Movements, and Reports pages must be verified to use Persian glyphs.

**Verification Method:**
1. Navigate to each module page
2. Inspect all numerical displays (stock levels, quantities, counts, totals)
3. Verify digits are Persian (۰-۹) not Latin (0-9)
4. Check browser developer tools for rendered HTML

**Modules to Verify:**
- [ ] Warehouse Inventory List (`/dwms/{id}/items/`)
- [ ] Warehouse Item Detail (`/dwms/{id}/items/{item_id}/`)
- [ ] Warehouse Dashboard (`/dwms/{id}/`)
- [ ] Lending List (`/dwms/{id}/lends/`)
- [ ] Lending Return (`/dwms/{id}/lends/{lend_id}/return/`)
- [ ] Movement History (`/dwms/{id}/movements/`)
- [ ] Location List (`/dwms/{id}/locations/`)
- [ ] Daily Reports (`/dwms/{id}/reports/daily/`)
- [ ] Weekly Reports (`/dwms/{id}/reports/weekly/`)
- [ ] Monthly Reports (`/dwms/{id}/reports/monthly/`)

### 5.2 Visual Alignment

**Requirement:** The typography must remain consistent; Persian digits must not cause row height changes or horizontal overflow in narrow table columns.

**Verification:**
- [ ] Table row heights remain consistent
- [ ] No horizontal overflow in narrow columns
- [ ] Text alignment preserved (RTL/LTR)
- [ ] Badge and label sizes remain appropriate
- [ ] Mobile responsive layout maintained

**CSS Considerations:**
- Font stack already includes Persian digit support: `'Vazirmatn', 'IRANSans', Tahoma, Arial, sans-serif`
- No additional CSS changes required
- Test with various screen sizes

### 5.3 Cross-Browser Rendering

**Requirement:** Localization must be tested on multiple browsers to ensure that the font-face correctly supports the extended Arabic-Indic character set.

**Browser Compatibility Testing:**
- [ ] Chrome/Edge (latest)
- [ ] Firefox (latest)
- [ ] Safari (latest)
- [ ] Mobile browsers (iOS Safari, Chrome Mobile)
- [ ] Older browsers with font fallback

**Test Scenarios:**
- [ ] Verify Persian digits render correctly
- [ ] Verify font fallback works if primary font unavailable
- [ ] Verify no mixed Latin/Persian digits
- [ ] Verify thousands separators display correctly

### 5.4 Performance Verification

**Requirement:** The localization logic must handle complex numerical strings without degrading performance.

**Performance Tests:**
- [ ] Page load time unchanged
- [ ] TTFB (Time to First Byte) unaffected
- [ ] Template rendering time acceptable
- [ ] No JavaScript errors
- [ ] No console warnings

**Benchmarking:**
- Test with large datasets (1000+ items, 500+ movements)
- Verify filter performance on aggregate operations
- Monitor server CPU and memory usage

### 5.5 Data Integrity Verification

**Requirement:** Backend data must remain as standard integers; localization must not affect database operations.

**Verification:**
- [ ] Database values remain as integers/floats
- [ ] Form submissions use standard integer format
- [ ] API responses contain standard integers (if applicable)
- [ ] Search functionality works with both Persian and Latin input
- [ ] Aggregation functions (`sum()`, `count()`, etc.) work correctly

---

## 6. Files Modified

### 6.1 Templates to Update

1. **`templates/dwms/item_list.html`**
   - Add `{% load persian_numbers %}`
   - Apply `persian_digits` filter to `total_stock`

2. **`templates/dwms/item_detail.html`**
   - Apply `persian_digits` filter to stock levels and thresholds

3. **`templates/dwms/dashboard.html`**
   - Apply `persian_digits` filter to statistics and movement quantities

4. **`templates/dwms/lend_list.html`**
   - Add `{% load persian_numbers %}`
   - Apply `persian_digits` filter to `quantity`

5. **`templates/dwms/lend_return.html`**
   - Add `{% load persian_numbers %}`
   - Apply `persian_digits` filter to `quantity`

6. **`templates/dwms/movement_history.html`**
   - Add `{% load persian_numbers %}`
   - Apply `persian_digits` filter to `quantity`

7. **`templates/dwms/location_list.html`**
   - Add `{% load persian_numbers %}`
   - Apply `persian_digits` filter to `item_count` and `total_items`

8. **`templates/dwms/lend_form.html`**
   - Add `{% load persian_numbers %}` (if stock availability is displayed)

### 6.2 Views to Verify (Search Functionality)

1. **`dwms/views.py`**
   - Verify search functionality in `item_list`, `movement_history`, `lend_list`
   - Apply normalization middleware if search exists

### 6.3 No Changes Required

- **`templates/dwms/reports_daily.html`** - Already implements Persian digits ✅
- **`tickets/templatetags/persian_numbers.py`** - Filter already implemented ✅

---

## 7. Testing Checklist

### 7.1 Functional Verification

- [ ] All stock levels display Persian digits
- [ ] All quantities display Persian digits
- [ ] All counts and totals display Persian digits
- [ ] Threshold values display Persian digits
- [ ] Movement quantities display Persian digits
- [ ] Report aggregates display Persian digits
- [ ] Zero values display as `۰`
- [ ] Large numbers display with thousands separators (if applicable)

### 7.2 Visual Verification

- [ ] Typography remains consistent
- [ ] No row height changes
- [ ] No horizontal overflow
- [ ] Badge sizes appropriate
- [ ] Mobile layout maintained
- [ ] RTL text alignment preserved

### 7.3 Browser Compatibility

- [ ] Chrome/Edge rendering correct
- [ ] Firefox rendering correct
- [ ] Safari rendering correct
- [ ] Mobile browsers rendering correct
- [ ] Font fallback works correctly

### 7.4 Performance Verification

- [ ] Page load time acceptable
- [ ] No performance degradation
- [ ] Large datasets render correctly
- [ ] No JavaScript errors
- [ ] No console warnings

### 7.5 Data Integrity

- [ ] Form submissions use standard integers
- [ ] Database values unchanged
- [ ] Search functionality works
- [ ] Aggregation functions work correctly
- [ ] API responses (if any) use standard integers

---

## 8. Maintenance Notes

### 8.1 Future Considerations

- **Export Functionality:** Implement export format selector (Persian/Latin) for Excel/PDF reports
- **Search Normalization:** Verify and implement search normalization in DWMS views if not already present
- **Pagination:** Consider custom template tag for Persian digit pagination numbers
- **JavaScript Displays:** Verify and update any JavaScript-rendered numerical values (e.g., `scan.html` line 428)

### 8.2 Code Comments

All template updates should include comments documenting the Persian digit localization:
```django
{# Stock level with Persian digits #}
{{ total_stock|floatformat:0|persian_digits }}
```

### 8.3 Backward Compatibility

- ✅ Existing functionality unchanged
- ✅ No breaking changes
- ✅ Optional enhancement (can be disabled by removing filter)
- ✅ No database migrations required
- ✅ Backend data integrity maintained

---

## 9. Implementation Summary

**Status:** ⚠️ **Partially Implemented**

**Completed:**
- ✅ Persian digits filter created (`persian_numbers.py`)
- ✅ Reports module fully localized (`reports_daily.html`)
- ✅ Date localization already implemented (`persian_date` filters)

**Pending:**
- ⚠️ Warehouse module templates need filter application
- ⚠️ Lending module templates need filter application
- ⚠️ Movements module templates need filter application
- ⚠️ Dashboard statistics need filter application
- ⚠️ Location list needs filter application
- ⚠️ Search normalization needs verification in DWMS views

**Next Steps:**
1. Apply `persian_digits` filter to all numerical displays in DWMS templates
2. Verify search functionality and apply normalization if needed
3. Test all modules for visual consistency and performance
4. Document export format requirements for future implementation

---

## 10. Conclusion

This specification provides a comprehensive guide for implementing system-wide numerical localization across all operational modules. The implementation follows the same architectural patterns established in the Dashboard and Identifier localization projects, ensuring consistency and maintainability. The transformation is one-way (presentation only), preserving backend data integrity while providing a fully localized user experience.



