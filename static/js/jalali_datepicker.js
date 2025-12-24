/**
 * Basic Jalali Date Picker Module
 * 
 * This is a basic, modular implementation that can be replaced with a formal API later.
 * It provides a simple interface for selecting Jalali dates.
 */

class JalaliDatePicker {
    constructor(inputElement, options = {}) {
        this.input = inputElement;
        this.options = {
            format: 'YYYY/MM/DD',
            minYear: 1300,
            maxYear: 1500,
            ...options
        };
        
        this.init();
    }
    
    init() {
        // Create a simple dropdown-based date picker
        this.createPicker();
    }
    
    createPicker() {
        // Create container for date picker
        const container = document.createElement('div');
        container.className = 'jalali-datepicker-container';
        container.style.display = 'flex';
        container.style.gap = '0.5rem';
        container.style.alignItems = 'center';
        container.style.flexWrap = 'wrap';
        
        // Year dropdown
        const yearSelect = document.createElement('select');
        yearSelect.className = 'form-select jalali-year';
        yearSelect.style.minWidth = '100px';
        
        // Month dropdown
        const monthSelect = document.createElement('select');
        monthSelect.className = 'form-select jalali-month';
        monthSelect.style.minWidth = '100px';
        
        // Day dropdown
        const daySelect = document.createElement('select');
        daySelect.className = 'form-select jalali-day';
        daySelect.style.minWidth = '100px';
        
        // Populate year dropdown
        const currentYear = new Date().getFullYear();
        const jalaliYear = this.gregorianToJalaliYear(currentYear);
        for (let year = this.options.minYear; year <= this.options.maxYear; year++) {
            const option = document.createElement('option');
            option.value = year;
            option.textContent = year;
            if (year === jalaliYear) option.selected = true;
            yearSelect.appendChild(option);
        }
        
        // Populate month dropdown
        const months = [
            'فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
            'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'
        ];
        months.forEach((month, index) => {
            const option = document.createElement('option');
            option.value = index + 1;
            option.textContent = month;
            monthSelect.appendChild(option);
        });
        
        // Populate day dropdown
        this.updateDayDropdown(daySelect, 1, 31);
        
        // Update days when year/month changes
        const updateDays = () => {
            const year = parseInt(yearSelect.value);
            const month = parseInt(monthSelect.value);
            const daysInMonth = this.getDaysInJalaliMonth(year, month);
            this.updateDayDropdown(daySelect, 1, daysInMonth);
            this.updateInput();
        };
        
        yearSelect.addEventListener('change', updateDays);
        monthSelect.addEventListener('change', updateDays);
        daySelect.addEventListener('change', () => this.updateInput());
        
        // Set initial value if input has value
        if (this.input.value) {
            this.setValue(this.input.value);
        }
        
        // Store references
        this.yearSelect = yearSelect;
        this.monthSelect = monthSelect;
        this.daySelect = daySelect;
        
        // Insert container after input
        container.appendChild(yearSelect);
        container.appendChild(monthSelect);
        container.appendChild(daySelect);
        this.input.parentNode.insertBefore(container, this.input.nextSibling);
        
        // Hide the original input (but keep it for form submission)
        this.input.style.display = 'none';
        
        // Update input value initially
        this.updateInput();
    }
    
    updateDayDropdown(select, min, max) {
        select.innerHTML = '';
        for (let day = min; day <= max; day++) {
            const option = document.createElement('option');
            option.value = day;
            option.textContent = day;
            select.appendChild(option);
        }
    }
    
    updateInput() {
        const year = this.yearSelect.value;
        const month = String(this.monthSelect.value).padStart(2, '0');
        const day = String(this.daySelect.value).padStart(2, '0');
        this.input.value = `${year}/${month}/${day}`;
    }
    
    setValue(dateString) {
        // Parse date string (format: YYYY/MM/DD)
        const parts = dateString.split('/');
        if (parts.length === 3) {
            this.yearSelect.value = parts[0];
            this.monthSelect.value = parseInt(parts[1]);
            const year = parseInt(parts[0]);
            const month = parseInt(parts[1]);
            const daysInMonth = this.getDaysInJalaliMonth(year, month);
            this.updateDayDropdown(this.daySelect, 1, daysInMonth);
            this.daySelect.value = parseInt(parts[2]);
            this.updateInput();
        }
    }
    
    getDaysInJalaliMonth(year, month) {
        // Jalali calendar has 31 days for first 6 months, 30 for next 5, and variable for last month
        if (month <= 6) return 31;
        if (month <= 11) return 30;
        // Month 12 (Esfand) - check if leap year
        return this.isJalaliLeapYear(year) ? 30 : 29;
    }
    
    isJalaliLeapYear(year) {
        // Simple leap year calculation for Jalali calendar
        // A year is leap if (year + 2346) % 128 <= 30
        return ((year + 2346) % 128) <= 30;
    }
    
    gregorianToJalaliYear(gregorianYear) {
        // Approximate conversion (for current year selection)
        // Jalali year ≈ Gregorian year - 621
        return gregorianYear - 621;
    }
}

// Export for use
if (typeof module !== 'undefined' && module.exports) {
    module.exports = JalaliDatePicker;
}






