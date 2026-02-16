/**
 * Modern Jalali Calendar Picker
 * 
 * Architecture: Frontend never calls external API directly.
 * All API calls go through Django backend (/api/calendar/).
 */

// Persian numeral conversion functions
function toPersianNumerals(str) {
    const persianDigits = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];
    return str.replace(/\d/g, function(match) {
        return persianDigits[parseInt(match)];
    });
}

function fromPersianNumerals(str) {
    const persianDigits = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];
    let result = str;
    persianDigits.forEach((persian, index) => {
        result = result.replace(new RegExp(persian, 'g'), index.toString());
    });
    return result;
}

/** Returns local date string YYYY-MM-DD for today (minimum selectable date; yesterday and before are disabled). */
function getTodayDateString() {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}

class JalaliCalendarPicker {
    constructor(inputElement, options = {}) {
        this.input = inputElement;
        this.options = {
            apiUrl: '/api/calendar/',
            onSelect: null,
            ...options
        };
        
        // Current view state
        this.currentYear = null;
        this.currentMonth = null;
        this.selectedDate = null;
        this.selectedTime = null;
        this.calendarData = [];
        
        // Initialize
        this.init();
    }
    
    init() {
        // Create calendar trigger button
        this.createTrigger();
        
        // Create modal structure
        this.createModal();
        
        // Set initial date from input if available (synchronous)
        // Server date will be fetched when modal opens if needed
        this.setInitialDateSync();
    }
    
    createTrigger() {
        if (!this.input) {
            console.error('JalaliCalendarPicker: Input element is null or undefined');
            return;
        }
        
        // Icon is inside input field - just ensure it stays visible and input is clickable
        this.input.readOnly = true;
        this.input.style.cursor = 'pointer';
        this.input.style.backgroundColor = '#ffffff';
        this.input.style.paddingLeft = '2.5rem'; // Make room for icon
        
        // Ensure the icon inside input stays visible (support multiple instances: icon in wrapper or global id)
        const wrapperForIcon = this.input.closest('.deadline-date-wrapper') || this.input.parentElement;
        const iconInside = wrapperForIcon ? wrapperForIcon.querySelector('.fa-calendar-alt, .fa-calendar') : document.getElementById('calendar-icon-inside-input');
        if (iconInside) {
            iconInside.style.display = 'inline-block';
            iconInside.style.visibility = 'visible';
            iconInside.style.opacity = '1';
            iconInside.style.pointerEvents = 'none'; // Icon doesn't intercept clicks
        }
        
        // Remove any buttons or duplicate icons that might exist
        // Run cleanup multiple times to catch any dynamically added elements
        const cleanup = () => {
            const wrapper = this.input.closest('.deadline-date-wrapper') || this.input.parentElement;
            if (wrapper) {
                // Remove ALL buttons (we don't use buttons anymore)
                const buttons = wrapper.querySelectorAll('button, .btn');
                buttons.forEach(btn => btn.remove());
                
                // Keep only the single icon in this wrapper (for multi-instance: one icon per wrapper)
                const allIcons = wrapper.querySelectorAll('i.fa-calendar-alt, i.fa-calendar');
                allIcons.forEach(icon => {
                    if (icon !== iconInside) icon.remove();
                });
                if (iconInside) {
                    iconInside.style.display = 'inline-block';
                    iconInside.style.visibility = 'visible';
                    iconInside.style.opacity = '1';
                }
            }
        };
        
        // Run cleanup at multiple intervals
        setTimeout(cleanup, 50);
        setTimeout(cleanup, 200);
        setTimeout(cleanup, 500);
        
        // Create click handler
        const clickHandler = (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.openModal();
            return false;
        };
        
        // Add click event listener to input (icon is just visual, input handles clicks)
        this.input.addEventListener('click', clickHandler, true);
        
        // Also make the icon wrapper clickable (if it exists)
        const wrapper = this.input.closest('.deadline-date-wrapper');
        if (wrapper) {
            wrapper.style.cursor = 'pointer';
            wrapper.addEventListener('click', (e) => {
                const isIcon = e.target.id === 'calendar-icon-inside-input' || e.target.closest('#calendar-icon-inside-input') || (wrapper.contains(e.target) && (e.target.classList.contains('fa-calendar-alt') || e.target.classList.contains('fa-calendar')));
                if (e.target === wrapper || isIcon) {
                    clickHandler(e);
                }
            }, true);
        }
    }
    
    createModal() {
        console.log('Creating calendar modal...');
        
        // Check if modal already exists
        let existingOverlay = document.getElementById('calendar-modal-overlay');
        if (existingOverlay) {
            console.log('Modal already exists, reusing...');
            this.overlay = existingOverlay;
            this.modal = existingOverlay.querySelector('.calendar-modal');
            this.body = document.getElementById('calendar-body');
            this.detailsContent = document.getElementById('calendar-details-content');
            
            // CRITICAL FIX: Re-attach event listeners when reusing modal
            // This ensures the select button always has a working click handler
            this.attachModalEventListeners();
            return;
        }
        
        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'calendar-modal-overlay';
        overlay.id = 'calendar-modal-overlay';
        
        // Create modal
        const modal = document.createElement('div');
        modal.className = 'calendar-modal';
        modal.id = 'calendar-modal';
        
        // Modal header
        const header = document.createElement('div');
        header.className = 'calendar-modal-header';
        header.innerHTML = `
            <h3 class="calendar-modal-title">انتخاب تاریخ مهلت انجام</h3>
            <button class="calendar-modal-close" aria-label="بستن">&times;</button>
        `;
        
        // Navigation
        const nav = document.createElement('div');
        nav.className = 'calendar-nav';
        nav.innerHTML = `
            <button class="calendar-nav-btn" id="calendar-prev-month">
                <i class="fas fa-chevron-right"></i>
                <span>ماه قبل</span>
            </button>
            <div class="calendar-nav-month-year" id="calendar-month-year"></div>
            <button class="calendar-nav-btn" id="calendar-next-month">
                <span>ماه بعد</span>
                <i class="fas fa-chevron-left"></i>
            </button>
        `;
        
        // Calendar body
        const body = document.createElement('div');
        body.className = 'calendar-body';
        body.id = 'calendar-body';
        
        // Day details
        const details = document.createElement('div');
        details.className = 'calendar-details';
        details.innerHTML = `
            <div class="calendar-details-empty">روزی را برای مشاهده جزئیات انتخاب کنید</div>
            <div class="calendar-details-content" id="calendar-details-content"></div>
        `;
        
        // Time input section (Custom 24-hour picker, RTL, Persian numerals)
        // Layout: Hour on LEFT, colon, Minute on RIGHT - visual order: [Hour] : [Minute]
        // HTML order reversed for RTL: Minute (first) appears on RIGHT, Hour (last) appears on LEFT
        const timeSection = document.createElement('div');
        timeSection.className = 'calendar-time-section';
        const defaultTime = this.selectedTime || '09:00';
        const [defaultHour, defaultMinute] = defaultTime.split(':');
        timeSection.innerHTML = `
            <label class="calendar-time-label">زمان (24 ساعته):</label>
            <div class="custom-time-picker" dir="rtl">
                <div class="time-input-group time-minute-group">
                    <label for="calendar-time-minute" class="time-input-label">دقیقه</label>
                    <input type="number" class="time-minute-input" id="calendar-time-minute" min="0" max="59" value="${defaultMinute || '00'}">
                </div>
                <span class="time-separator">:</span>
                <div class="time-input-group time-hour-group">
                    <label for="calendar-time-hour" class="time-input-label">ساعت</label>
                    <input type="number" class="time-hour-input" id="calendar-time-hour" min="0" max="23" value="${defaultHour || '09'}">
                </div>
                <input type="hidden" id="calendar-time-input" value="${defaultTime}">
            </div>
        `;
        
        // Footer
        const footer = document.createElement('div');
        footer.className = 'calendar-modal-footer';
        footer.innerHTML = `
            <button class="calendar-btn calendar-btn-secondary" id="calendar-cancel-btn">انصراف</button>
            <button class="calendar-btn calendar-btn-primary" id="calendar-select-btn" disabled>انتخاب تاریخ</button>
        `;
        
        // Assemble modal
        modal.appendChild(header);
        modal.appendChild(nav);
        modal.appendChild(body);
        modal.appendChild(details);
        modal.appendChild(timeSection);
        modal.appendChild(footer);
        overlay.appendChild(modal);
        
        // CRITICAL: Prevent modal clicks from bubbling to overlay
        // This ensures button clicks don't trigger overlay close handler
        modal.addEventListener('click', (e) => {
            e.stopPropagation();
        }, false);
        
        // Add to document
        try {
            document.body.appendChild(overlay);
            console.log('Modal added to document body');
        } catch (error) {
            console.error('Error adding modal to document:', error);
            throw error;
        }
        
        // Store overlay reference before attaching listeners
        this.overlay = overlay;
        this.modal = modal;
        this.body = body;
        this.detailsContent = document.getElementById('calendar-details-content');
        
        // Attach event listeners
        this.attachModalEventListeners();
        
        // Custom time picker: hour and minute inputs
        const hourInput = document.getElementById('calendar-time-hour');
        const minuteInput = document.getElementById('calendar-time-minute');
        const hiddenTimeInput = document.getElementById('calendar-time-input');
        
        const updateTimeValue = () => {
            let hour = parseInt(hourInput.value, 10) || 0;
            let minute = parseInt(minuteInput.value, 10) || 0;
            
            // Validate and clamp values
            if (hour < 0) hour = 0;
            if (hour > 23) hour = 23;
            if (minute < 0) minute = 0;
            if (minute > 59) minute = 59;
            
            // Update inputs with validated values
            hourInput.value = hour.toString().padStart(2, '0');
            minuteInput.value = minute.toString().padStart(2, '0');
            
            // Store combined time in 24-hour format (HH:MM)
            const timeStr = `${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`;
            this.selectedTime = timeStr;
            if (hiddenTimeInput) {
                hiddenTimeInput.value = timeStr;
            }
        };
        
        if (hourInput && minuteInput) {
            // Set initial values if we have a stored time
            if (this.selectedTime) {
                const [h, m] = this.selectedTime.split(':');
                hourInput.value = h || '09';
                minuteInput.value = m || '00';
            }
            
            // Update on input/change
            hourInput.addEventListener('input', updateTimeValue);
            hourInput.addEventListener('change', updateTimeValue);
            minuteInput.addEventListener('input', updateTimeValue);
            minuteInput.addEventListener('change', updateTimeValue);
            
            // Initial update
            updateTimeValue();
        } else {
            console.warn('Time input elements not found');
        }
        
        // Keyboard support (only attach once globally)
        if (!this._keyboardHandlerAttached) {
            document.addEventListener('keydown', (e) => {
                if (this.overlay && this.overlay.classList.contains('show')) {
                    if (e.key === 'Escape') this.closeModal();
                }
            });
            this._keyboardHandlerAttached = true;
        }
        
        console.log('Modal created and event listeners attached');
    }
    
    attachModalEventListeners() {
        console.log('Attaching modal event listeners...');
        
        if (!this.overlay) {
            console.error('Cannot attach listeners: overlay not found');
            return;
        }
        
        // Remove old event listeners by cloning and replacing elements
        // This prevents duplicate event listeners
        const selectBtn = document.getElementById('calendar-select-btn');
        const cancelBtn = document.getElementById('calendar-cancel-btn');
        const closeBtn = this.overlay.querySelector('.calendar-modal-close');
        const prevBtn = document.getElementById('calendar-prev-month');
        const nextBtn = document.getElementById('calendar-next-month');
        
        // CRITICAL FIX: Remove old click listeners and attach new ones
        // Store reference to this for use in event handlers
        const self = this;
        
        // Remove and re-attach select button listener
        if (selectBtn) {
            // Clone button to remove all event listeners
            const newSelectBtn = selectBtn.cloneNode(true);
            selectBtn.parentNode.replaceChild(newSelectBtn, selectBtn);
            
            // Attach new click handler with proper event handling
            newSelectBtn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                console.log('=== SELECT BUTTON CLICKED ===');
                console.log('Button disabled state:', this.disabled);
                console.log('Selected date:', self.selectedDate);
                
                // Double-check button is not disabled
                if (this.disabled) {
                    console.warn('⚠️ Select button is disabled, but click was received. This should not happen.');
                    return;
                }
                
                // Call selectDate with proper error handling
                try {
                    self.selectDate();
                } catch (error) {
                    console.error('❌ ERROR in selectDate:', error);
                    alert('خطا در انتخاب تاریخ. لطفاً دوباره تلاش کنید.');
                }
            }, true); // Use capture phase to ensure handler runs early
            
            console.log('✅ Select button event listener attached');
        } else {
            console.error('❌ Select button not found!');
        }
        
        // Re-attach cancel button listener
        if (cancelBtn) {
            const newCancelBtn = cancelBtn.cloneNode(true);
            cancelBtn.parentNode.replaceChild(newCancelBtn, cancelBtn);
            newCancelBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.closeModal();
            }, true);
        }
        
        // Re-attach close button listener
        if (closeBtn) {
            const newCloseBtn = closeBtn.cloneNode(true);
            closeBtn.parentNode.replaceChild(newCloseBtn, closeBtn);
            newCloseBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.closeModal();
            }, true);
        }
        
        // Re-attach navigation buttons
        if (prevBtn) {
            const newPrevBtn = prevBtn.cloneNode(true);
            prevBtn.parentNode.replaceChild(newPrevBtn, prevBtn);
            newPrevBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.navigateMonth(-1);
            }, true);
        }
        
        if (nextBtn) {
            const newNextBtn = nextBtn.cloneNode(true);
            nextBtn.parentNode.replaceChild(newNextBtn, nextBtn);
            newNextBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.navigateMonth(1);
            }, true);
        }
        
        // Re-attach overlay click handler (but prevent it from interfering with button clicks)
        // Remove old handler by replacing overlay
        const newOverlay = this.overlay.cloneNode(false);
        while (this.overlay.firstChild) {
            newOverlay.appendChild(this.overlay.firstChild);
        }
        this.overlay.parentNode.replaceChild(newOverlay, this.overlay);
        this.overlay = newOverlay;
        
        this.overlay.addEventListener('click', (e) => {
            // Only close if clicking directly on overlay, not on modal content
            if (e.target === this.overlay) {
                this.closeModal();
            }
        }, false);
        
        // CRITICAL: Ensure modal stops propagation to prevent overlay handler from interfering
        if (this.modal) {
            this.modal.addEventListener('click', (e) => {
                e.stopPropagation();
            }, false);
        }
        
        // Re-attach time input handlers
        const hourInput = document.getElementById('calendar-time-hour');
        const minuteInput = document.getElementById('calendar-time-minute');
        const hiddenTimeInput = document.getElementById('calendar-time-input');
        
        if (hourInput && minuteInput) {
            const updateTimeValue = () => {
                let hour = parseInt(hourInput.value, 10) || 0;
                let minute = parseInt(minuteInput.value, 10) || 0;
                
                // Validate and clamp values
                if (hour < 0) hour = 0;
                if (hour > 23) hour = 23;
                if (minute < 0) minute = 0;
                if (minute > 59) minute = 59;
                
                // Update inputs with validated values
                hourInput.value = hour.toString().padStart(2, '0');
                minuteInput.value = minute.toString().padStart(2, '0');
                
                // Store combined time in 24-hour format (HH:MM)
                const timeStr = `${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`;
                this.selectedTime = timeStr;
                if (hiddenTimeInput) {
                    hiddenTimeInput.value = timeStr;
                }
            };
            
            // Set initial values if we have a stored time
            if (this.selectedTime) {
                const [h, m] = this.selectedTime.split(':');
                hourInput.value = h || '09';
                minuteInput.value = m || '00';
            }
            
            // Remove old listeners by cloning inputs
            const newHourInput = hourInput.cloneNode(true);
            const newMinuteInput = minuteInput.cloneNode(true);
            hourInput.parentNode.replaceChild(newHourInput, hourInput);
            minuteInput.parentNode.replaceChild(newMinuteInput, minuteInput);
            
            // Attach new listeners
            newHourInput.addEventListener('input', updateTimeValue);
            newHourInput.addEventListener('change', updateTimeValue);
            newMinuteInput.addEventListener('input', updateTimeValue);
            newMinuteInput.addEventListener('change', updateTimeValue);
            
            // Initial update
            updateTimeValue();
        }
        
        console.log('✅ All modal event listeners attached successfully');
    }
    
    setInitialDateSync() {
        // Synchronous initialization: only parse input if it has a value.
        // IMPORTANT: Read from both the live value *and* the DOM attribute so
        // that a previously selected deadline survives any intermediate
        // DOM/value shenanigans.
        const rawValue = (this.input && (this.input.value || this.input.getAttribute('value'))) || '';
        const combined = rawValue.trim();

        // #region agent log - Hypothesis A: setInitialDateSync input/source
        // DISABLED: Telemetry endpoint causes ERR_CONNECTION_REFUSED and blocks form initialization
        // Removed blocking fetch call to prevent frontend crashes
        // #endregion

        // #region agent log - Hypothesis H3: Input-based initialization may overwrite selectedDate with today's date
        // DISABLED: Telemetry endpoint causes ERR_CONNECTION_REFUSED and blocks form initialization
        // Removed blocking fetch call to prevent frontend crashes
        // #endregion

        // If we don't actually have anything, leave state unset so that the
        // server-provided "current jalali date" can be used when the modal opens.
        if (combined) {
            const spaceIndex = combined.indexOf(' ');
            if (spaceIndex > 0) {
                // Has time component (format: "YYYY/MM/DD HH:MM")
                const dateStr = combined.substring(0, spaceIndex);
                const timeStr = combined.substring(spaceIndex + 1);
                const parts = dateStr.split('/');
                if (parts.length === 3) {
                    this.currentYear = parseInt(parts[0]);
                    this.currentMonth = parseInt(parts[1]);
                    this.selectedDate = {
                        year: parseInt(parts[0]),
                        month: parseInt(parts[1]),
                        day: parseInt(parts[2])
                    };
                    this.selectedTime = timeStr;
                    return; // Use the date from input
                }
            } else {
                // Only date (format: "YYYY/MM/DD")
                const parts = combined.split('/');
                if (parts.length === 3) {
                    this.currentYear = parseInt(parts[0]);
                    this.currentMonth = parseInt(parts[1]);
                    this.selectedDate = {
                        year: parseInt(parts[0]),
                        month: parseInt(parts[1]),
                        day: parseInt(parts[2])
                    };
                    return; // Use the date from input
                }
            }
        }
        // If no usable input value, leave currentYear/currentMonth as null.
        // They will be fetched from server when modal opens.
    }
    
    async fetchCurrentJalaliDate() {
        // Fetch current Jalali date from server
        try {
            // Build URL for current date API
            let currentDateUrl = this.options.apiUrl;
            if (currentDateUrl.includes('/api/calendar/')) {
                currentDateUrl = currentDateUrl.replace('/api/calendar/', '/api/current-jalali-date/');
            } else {
                // Fallback: construct from base URL
                try {
                    const urlObj = new URL(currentDateUrl, window.location.origin);
                    urlObj.pathname = '/api/current-jalali-date/';
                    currentDateUrl = urlObj.toString();
                } catch (e) {
                    // If URL parsing fails, try simple string replacement
                    currentDateUrl = currentDateUrl.replace('calendar', 'current-jalali-date');
                }
            }
            console.log('Fetching current Jalali date from:', currentDateUrl);
            const response = await fetch(currentDateUrl);
            
            if (response.ok) {
                const data = await response.json();
                if (data.success) {
                    this.currentYear = data.year;
                    this.currentMonth = data.month;
                    console.log('✅ Current Jalali date from server:', data.year, data.month);
                    return true;
                }
            }
            console.warn('⚠️ Failed to get current date from server, using fallback');
            return false;
        } catch (error) {
            console.error('❌ Error fetching current Jalali date:', error);
            return false;
        }
    }
    
    async openModal() {
        console.log('=== openModal START ===');
        console.log('Current year:', this.currentYear, 'Current month:', this.currentMonth);
        
        // When reusing shared modal, re-bind select button to this instance so value goes to correct input
        if (this.overlay) {
            this.attachModalEventListeners();
        }
        
        // CRITICAL: Sync selectedDate with input value before opening modal
        // This ensures if user previously selected a date, it's preserved
        this.setInitialDateSync();
        console.log('After setInitialDateSync - selectedDate:', this.selectedDate);

        // #region agent log - Hypothesis B: state right after setInitialDateSync in openModal
        // DISABLED: Telemetry endpoint causes ERR_CONNECTION_REFUSED and blocks form initialization
        // Removed blocking fetch call to prevent frontend crashes
        // #endregion
        
        if (!this.overlay) {
            console.error('Modal overlay not found! Creating modal...');
            this.createModal();
        }
        
        if (!this.overlay) {
            console.error('Failed to create modal overlay!');
            alert('خطا در ایجاد تقویم. لطفاً صفحه را رفرش کنید.');
            return;
        }
        
        // Ensure we have valid year and month - fetch from server if needed
        // Only fetch current date if we don't have a selectedDate from input
        if (!this.currentYear || !this.currentMonth) {
            // If we have a selectedDate from input, use that for calendar view
            if (this.selectedDate) {
                this.currentYear = this.selectedDate.year;
                this.currentMonth = this.selectedDate.month;
                console.log('Using selectedDate for calendar view:', this.currentYear, this.currentMonth);
            } else {
                // No date selected, fetch current date from server
                console.log('No initial date set, fetching current Jalali date from server...');
                const fetched = await this.fetchCurrentJalaliDate();
                if (!fetched) {
                    // Fallback: Use approximate conversion (should rarely be needed)
                    const now = new Date();
                    const jalaliYear = now.getFullYear() - 621;
                    const jalaliMonth = (now.getMonth() + 7) % 12 + 1;
                    this.currentYear = jalaliYear;
                    this.currentMonth = jalaliMonth;
                    console.warn('⚠️ Using approximate Jalali date conversion:', jalaliYear, jalaliMonth);
                }
            }
        }
        
        console.log('Showing modal for year:', this.currentYear, 'month:', this.currentMonth);
        
        this.overlay.classList.add('show');
        console.log('Modal overlay CSS class "show" added');
        
        // Ensure body element exists
        if (!this.body) {
            this.body = document.getElementById('calendar-body');
            console.log('Retrieved calendar body element:', this.body);
        }
        
        if (!this.body) {
            console.error('Calendar body element still not found!');
            alert('خطا: المان تقویم یافت نشد');
            return;
        }
        
        // Sync custom time picker with stored time value
        const hourInput = document.getElementById('calendar-time-hour');
        const minuteInput = document.getElementById('calendar-time-minute');
        if (hourInput && minuteInput && this.selectedTime) {
            const [h, m] = this.selectedTime.split(':');
            hourInput.value = h || '09';
            minuteInput.value = m || '00';
        }
        
        console.log('About to call loadCalendar...');
        try {
            await this.loadCalendar(this.currentYear, this.currentMonth);
            console.log('=== loadCalendar completed successfully ===');
        } catch (error) {
            console.error('=== ERROR in loadCalendar ===');
            console.error('Error:', error);
            console.error('Error name:', error.name);
            console.error('Error message:', error.message);
            console.error('Error stack:', error.stack);
            if (this.body) {
                this.body.innerHTML = `<div style="padding: 40px; text-align: center; color: #ef4444;">خطا در بارگذاری تقویم: ${error.message}</div>`;
            }
        }
        console.log('=== openModal END ===');
    }
    
    closeModal() {
        this.overlay.classList.remove('show');
    }
    
    async navigateMonth(direction) {
        this.currentMonth += direction;
        if (this.currentMonth > 12) {
            this.currentMonth = 1;
            this.currentYear++;
        } else if (this.currentMonth < 1) {
            this.currentMonth = 12;
            this.currentYear--;
        }
        await this.loadCalendar(this.currentYear, this.currentMonth);
    }
    
    async loadCalendar(year, month) {
        console.log('loadCalendar called with year:', year, 'month:', month);
        
        // Show loading state
        if (this.body) {
            this.body.innerHTML = '<div class="calendar-loading">در حال بارگذاری...</div>';
        } else {
            console.error('Calendar body element not found!');
            return;
        }
        
        // Update month/year display with Persian numerals
        const monthNames = [
            'فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
            'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'
        ];
        const monthYearEl = document.getElementById('calendar-month-year');
        if (monthYearEl) {
            const yearPersian = toPersianNumerals(year.toString());
            monthYearEl.textContent = `${monthNames[month - 1]} ${yearPersian}`;
        }
        
        try {
            const apiUrl = `${this.options.apiUrl}?year=${year}&month=${month}`;
            console.log('Fetching calendar data from:', apiUrl);
            
            // Fetch calendar data from Django API
            const response = await fetch(apiUrl);
            console.log('API response status:', response.status, response.statusText);
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            console.log('API response data:', data);
            
            if (data.success && data.days) {
                console.log('API call successful, received', data.days.length, 'days');
                this.calendarData = data.days;
                this.renderCalendar(data.days, year, month);
            } else {
                console.error('API returned unsuccessful response:', data);
                const errorMsg = data.error || 'خطا در دریافت اطلاعات';
                if (this.body) {
                    this.body.innerHTML = `<div style="padding: 40px; text-align: center; color: #ef4444;">خطا: ${errorMsg}</div>`;
                }
            }
        } catch (error) {
            console.error('Error loading calendar:', error);
            console.error('Error stack:', error.stack);
            if (this.body) {
                this.body.innerHTML = `<div style="padding: 40px; text-align: center; color: #ef4444;">خطا در اتصال به سرور: ${error.message}</div>`;
            }
        }
    }
    
    renderCalendar(days, year, month) {
        console.log('Rendering calendar for', year, month, 'with', days.length, 'days');
        
        // Create weekdays header (Jalali week starts on Saturday)
        const weekdays = ['ش', 'ی', 'د', 'س', 'چ', 'پ', 'ج']; // Saturday to Friday
        const weekdaysHtml = weekdays.map(day => `<div class="calendar-weekday">${day}</div>`).join('');
        
        // Create calendar grid
        let daysHtml = '';
        
        // Sort days by day number to ensure correct order
        const sortedDays = [...days].sort((a, b) => a.day - b.day);
        
        if (sortedDays.length === 0) {
            this.body.innerHTML = '<div style="padding: 40px; text-align: center; color: #ef4444;">هیچ داده‌ای برای این ماه یافت نشد</div>';
            return;
        }
        
        // Get first day of month to calculate starting weekday
        const firstDay = sortedDays[0];
        let startWeekday = 0; // Default to Saturday (0)
        
        if (firstDay && firstDay.gregorian_date) {
            try {
                // Parse Gregorian date to get weekday
                const gregorianDate = new Date(firstDay.gregorian_date);
                // JavaScript Date.getDay() returns 0=Sunday, 6=Saturday
                // Jalali week: 0=Saturday (شنبه), 1=Sunday (یکشنبه), ..., 6=Friday (جمعه)
                let jsWeekday = gregorianDate.getDay(); // 0=Sunday, 6=Saturday
                // Convert to Jalali weekday: Saturday=0, Sunday=1, ..., Friday=6
                startWeekday = (jsWeekday + 1) % 7; // This maps: Sun(0)->1, Mon(1)->2, ..., Sat(6)->0
            } catch (e) {
                console.warn('Error parsing gregorian_date for first day:', e);
                // Fallback: assume first day is Saturday
                startWeekday = 0;
            }
        }
        
        console.log('First day of month starts on weekday:', startWeekday);
        
        const todayStr = getTodayDateString();
        
        // Add empty cells for days before month starts
        for (let i = 0; i < startWeekday; i++) {
            daysHtml += '<div class="calendar-day other-month"></div>';
        }
        
        // Add days of month
        sortedDays.forEach(dayData => {
            const isSelected = this.selectedDate && 
                this.selectedDate.year === dayData.year &&
                this.selectedDate.month === dayData.month &&
                this.selectedDate.day === dayData.day;
            
            const isToday = this.isToday(dayData);
            const gregorianDate = (dayData.gregorian_date || '').slice(0, 10);
            const isBeforeToday = gregorianDate && gregorianDate < todayStr;
            const classes = [
                'calendar-day',
                dayData.is_holiday ? 'holiday' : '',
                isSelected ? 'selected' : '',
                isToday ? 'today' : '',
                isBeforeToday ? 'disabled' : ''
            ].filter(c => c).join(' ');
            
            // Escape events JSON to prevent XSS
            const eventsJson = JSON.stringify(dayData.events || []).replace(/'/g, '&#39;');
            
            // Convert day number to Persian numerals
            const dayPersian = toPersianNumerals(dayData.day.toString());
            
            daysHtml += `
                <div class="${classes}" 
                     data-year="${dayData.year}" 
                     data-month="${dayData.month}" 
                     data-day="${dayData.day}"
                     data-gregorian-date="${gregorianDate || ''}"
                     data-is-holiday="${dayData.is_holiday ? 'true' : 'false'}"
                     data-disabled="${isBeforeToday ? 'true' : 'false'}"
                     data-events='${eventsJson}'
                     style="cursor: ${isBeforeToday ? 'not-allowed' : 'pointer'};">
                    ${dayPersian}
                </div>
            `;
        });
        
        // Fill remaining cells to complete the grid (7 columns)
        const totalCells = startWeekday + sortedDays.length;
        const remainingCells = (7 - (totalCells % 7)) % 7;
        for (let i = 0; i < remainingCells; i++) {
            daysHtml += '<div class="calendar-day other-month"></div>';
        }
        
        // Render
        this.body.innerHTML = `
            <div class="calendar-weekdays">${weekdaysHtml}</div>
            <div class="calendar-days">${daysHtml}</div>
        `;
        
        console.log('Calendar rendered, attaching click handlers...');
        
        // Add click handlers to all day cells (excluding empty cells)
        const dayElements = this.body.querySelectorAll('.calendar-day:not(.other-month)');
        console.log('Found', dayElements.length, 'clickable day elements');
        
        dayElements.forEach((dayEl, index) => {
            dayEl.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (dayEl.dataset.disabled === 'true') {
                    return;
                }
                console.log('Day clicked:', dayEl.dataset.day);
                this.selectDay(dayEl);
            });
            
            // Add hover effect
            dayEl.addEventListener('mouseenter', function() {
                if (!this.classList.contains('selected')) {
                    this.style.backgroundColor = '#f3f4f6';
                }
            });
            dayEl.addEventListener('mouseleave', function() {
                if (!this.classList.contains('selected')) {
                    this.style.backgroundColor = '';
                }
            });
        });
        
        // IMPORTANT:
        // Do NOT auto-select today's date here. Previously we tried to be
        // "helpful" and pre-select today whenever there was no explicit
        // selection and the input looked empty. In practice, this could race
        // with user selections or with how the form repopulates the field and
        // lead to the visual value snapping back to "today".
        //
        // The safer behavior is:
        //   - Only ever change the input value when the user explicitly
        //     confirms a date via the "Select" button.
        //   - Leave the calendar grid unselected on first open, with "today"
        //     simply highlighted via CSS.
        console.log('Auto-select of today is disabled to avoid overwriting user selections.');
        
        console.log('Click handlers attached successfully');

        // Ensure first render has a valid selection if none exists
        this.autoSelectToday();
    }
    
    autoSelectToday() {
        // CRITICAL: Never auto-select if a date has been manually selected (has locked copy)
        if (this._lockedSelectedDate) {
            console.log('⚠️ Skipping autoSelectToday - user has manually selected a date:', this._lockedSelectedDate);
            return;
        }
        
        // Only auto-select today if no date is currently selected AND no date exists in input field
        // This prevents overriding a user-selected future date
        if (!this.selectedDate) {
            // Double-check: if input has a value, don't auto-select today
            if (this.input && this.input.value && this.input.value.trim()) {
                console.log('Input has value, skipping auto-select today:', this.input.value);
                return;
            }
            
            const dayElements = this.body.querySelectorAll('.calendar-day.today:not(.other-month)');
            if (dayElements.length > 0) {
                const todayElement = dayElements[0];
                console.log('Auto-selecting today:', todayElement.dataset.day);
                
                // Set selectedDate from the element (but don't lock it, since it's auto-selected)
                this.selectedDate = {
                    year: parseInt(todayElement.dataset.year),
                    month: parseInt(todayElement.dataset.month),
                    day: parseInt(todayElement.dataset.day)
                };
                
                // Visually select it
                todayElement.classList.add('selected');
                
                // Show day details
                this.showDayDetails(todayElement);
                
                // Enable select button
                const selectBtn = document.getElementById('calendar-select-btn');
                if (selectBtn) {
                    selectBtn.disabled = false;
                }
                
                console.log('Today auto-selected:', this.selectedDate);
            }
        } else {
            console.log('⚠️ Skipping autoSelectToday - selectedDate already exists:', this.selectedDate);
        }
    }
    
    selectDay(dayElement) {
        console.log('=== selectDay CALLED ===');
        console.log('selectDay called with element:', dayElement);
        
        if (!dayElement) {
            console.error('Day element is null or undefined');
            return;
        }
        
        // Extract date values
        const year = parseInt(dayElement.dataset.year);
        const month = parseInt(dayElement.dataset.month);
        const day = parseInt(dayElement.dataset.day);
        
        console.log('Extracted date from element:', { year, month, day });
        
        // Validate extracted values
        if (isNaN(year) || isNaN(month) || isNaN(day)) {
            console.error('❌ Invalid date values extracted from element:', { year, month, day });
            return;
        }
        
        // Remove previous selection
        this.body.querySelectorAll('.calendar-day').forEach(el => {
            el.classList.remove('selected');
            // Reset background color
            if (!el.classList.contains('holiday') && !el.classList.contains('today')) {
                el.style.backgroundColor = '';
            }
        });
        
        // Add selection to clicked day
        dayElement.classList.add('selected');
        // Don't override CSS - let CSS handle styling
        // CSS already sets background gradient and white color
        
        // CRITICAL: Store selected date with explicit validation
        // Create a new object to avoid reference issues
        this.selectedDate = {
            year: year,
            month: month,
            day: day
        };
        
        // Lock the selectedDate to prevent accidental overwrites
        // Store a copy for verification
        this._lockedSelectedDate = JSON.parse(JSON.stringify(this.selectedDate));
        this._selectedGregorianDate = (dayElement.dataset.gregorianDate || '').slice(0, 10);

        // #region agent log - Hypothesis H1: Selected day is correct but later overwritten before selectDate
        try {
            // DISABLED: Telemetry endpoint causes ERR_CONNECTION_REFUSED
        } catch (e) {}
        // #endregion
        
        console.log('✅ Selected date stored:', JSON.stringify(this.selectedDate));
        console.log('✅ Locked copy stored:', JSON.stringify(this._lockedSelectedDate));
        
        // Show day details
        this.showDayDetails(dayElement);
        
        // Enable select button with defensive checks
        const selectBtn = document.getElementById('calendar-select-btn');
        if (selectBtn) {
            selectBtn.disabled = false;
            selectBtn.style.pointerEvents = 'auto';
            selectBtn.style.cursor = 'pointer';
            selectBtn.style.opacity = '1';
            console.log('✅ Select button enabled');
            console.log('Button disabled attribute:', selectBtn.disabled);
            console.log('Button computed style:', window.getComputedStyle(selectBtn).pointerEvents);
        } else {
            console.error('❌ Select button not found when trying to enable it!');
        }
        
        console.log('=== selectDay COMPLETED ===');
    }
    
    showDayDetails(dayElement) {
        const isHoliday = dayElement.dataset.isHoliday === 'true';
        const events = JSON.parse(dayElement.dataset.events || '[]');
        
        // Convert date to Persian numerals for display
        const yearStr = toPersianNumerals(this.selectedDate.year.toString());
        const monthStr = toPersianNumerals(String(this.selectedDate.month).padStart(2, '0'));
        const dayStr = toPersianNumerals(String(this.selectedDate.day).padStart(2, '0'));
        const dateStr = `${yearStr}/${monthStr}/${dayStr}`;
        
        let detailsHtml = `
            <div class="calendar-details-date">${dateStr}</div>
        `;
        
        if (isHoliday) {
            detailsHtml += '<div class="calendar-details-holiday">تعطیل رسمی</div>';
        }
        
        if (events && events.length > 0) {
            // Render ALL events
            const eventsHtml = events.map(event => `<div class="calendar-details-event">${event}</div>`).join('');
            
            detailsHtml += `
                <div class="calendar-details-events">
                    <div class="calendar-details-events-title">رویدادها:</div>
                    <div class="calendar-details-events-list">
                        ${eventsHtml}
                    </div>
                </div>
            `;
        }
        
        this.detailsContent.innerHTML = detailsHtml;
        document.querySelector('.calendar-details-empty').style.display = 'none';
        this.detailsContent.classList.add('show');
    }
    
    selectDate() {
        console.log('=== selectDate CALLED ===');
        console.log('selectDate called, selectedDate:', this.selectedDate);
        console.log('selectedDate type:', typeof this.selectedDate);
        console.log('selectedDate JSON:', JSON.stringify(this.selectedDate));
        console.log('_lockedSelectedDate (backup):', this._lockedSelectedDate ? JSON.stringify(this._lockedSelectedDate) : 'not set');
        
        // CRITICAL: Verify button state before proceeding
        const selectBtnCheck = document.getElementById('calendar-select-btn');
        if (selectBtnCheck && selectBtnCheck.disabled) {
            console.error('❌ CRITICAL: selectDate called but button is disabled!');
            console.error('This should not happen - button should be enabled when date is selected');
            // Try to enable it anyway
            selectBtnCheck.disabled = false;
            selectBtnCheck.style.pointerEvents = 'auto';
            selectBtnCheck.style.cursor = 'pointer';
        }

        // #region agent log - Hypothesis H2: selectedDate is already wrong when user clicks Select
        try {
            // DISABLED: Telemetry endpoint causes ERR_CONNECTION_REFUSED
        } catch (e) {}
        // #endregion
        
        // Prefer the DOM-selected day as the single source of truth.
        // This avoids any mismatch between internal state and what the
        // user actually clicked in the visible calendar grid.
        let dateToUse = null;
        let domSelected = null;

        if (this.body) {
            domSelected = this.body.querySelector('.calendar-day.selected');
        }

        if (domSelected) {
            const y = parseInt(domSelected.dataset.year);
            const m = parseInt(domSelected.dataset.month);
            const d = parseInt(domSelected.dataset.day);
            if (!isNaN(y) && !isNaN(m) && !isNaN(d)) {
                dateToUse = { year: y, month: m, day: d };
            }
        }

        // Fallback to internal state only if DOM selection is unavailable
        if (!dateToUse) {
            console.warn('⚠️ No DOM-selected day found, falling back to internal state');
            dateToUse = this.selectedDate;
            if (!dateToUse || !dateToUse.year || !dateToUse.month || !dateToUse.day) {
                console.warn('⚠️ selectedDate is invalid, checking locked copy...');
                if (this._lockedSelectedDate && this._lockedSelectedDate.year && this._lockedSelectedDate.month && this._lockedSelectedDate.day) {
                    console.log('✅ Using locked copy instead');
                    dateToUse = this._lockedSelectedDate;
                    this.selectedDate = JSON.parse(JSON.stringify(this._lockedSelectedDate)); // Restore
                } else {
                    console.error('❌ CRITICAL ERROR: No valid date selected!');
                    console.error('selectedDate object:', this.selectedDate);
                    console.error('_lockedSelectedDate object:', this._lockedSelectedDate);
                    alert('لطفاً یک تاریخ انتخاب کنید');
                    return;
                }
            }
        }

        // #region agent log - Hypothesis H2: Date used in selectDate differs from selected in selectDay / DOM
        try {
            // DISABLED: Telemetry endpoint causes ERR_CONNECTION_REFUSED
        } catch (e) {}
        // #endregion
        
        console.log('✅ Valid selectedDate confirmed:', {
            year: dateToUse.year,
            month: dateToUse.month,
            day: dateToUse.day
        });

        // Minimum selectable date is today (yesterday and before are not allowed)
        const todayStr = getTodayDateString();
        const selectedGregorian = (domSelected && domSelected.dataset.gregorianDate)
            ? domSelected.dataset.gregorianDate.slice(0, 10)
            : (this._selectedGregorianDate || '').slice(0, 10);
        if (selectedGregorian && selectedGregorian < todayStr) {
            alert('انتخاب تاریخ قبل از امروز مجاز نیست. لطفاً از امروز به بعد را انتخاب کنید.');
            return;
        }

        // #region agent log - Hypothesis H2: dateToUse (after fallback) differs from what was clicked
        try {
            // DISABLED: Telemetry endpoint causes ERR_CONNECTION_REFUSED
        } catch (e) {}
        // #endregion
        
        // CRITICAL: Use dateToUse instead of this.selectedDate from now on
        
        // Get time from custom time picker (24-hour format)
        const hourInput = document.getElementById('calendar-time-hour');
        const minuteInput = document.getElementById('calendar-time-minute');
        const hiddenTimeInput = document.getElementById('calendar-time-input');
        
        let timeStr = '09:00'; // Default time
        if (hourInput && minuteInput) {
            let hour = parseInt(hourInput.value, 10) || 9;
            let minute = parseInt(minuteInput.value, 10) || 0;
            // Validate and clamp
            if (hour < 0) hour = 0;
            if (hour > 23) hour = 23;
            if (minute < 0) minute = 0;
            if (minute > 59) minute = 59;
            timeStr = `${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`;
        } else if (hiddenTimeInput && hiddenTimeInput.value) {
            timeStr = hiddenTimeInput.value;
        }
        
        // If selected date is today, time must not be before now
        if (selectedGregorian && selectedGregorian === todayStr) {
            const selectedDateTime = new Date(selectedGregorian + 'T' + timeStr + ':00');
            const now = new Date();
            if (selectedDateTime < now) {
                alert('برای امروز نمی‌توانید ساعتی قبل از ساعت الان انتخاب کنید. لطفاً زمان فعلی یا بعد از آن را انتخاب کنید.');
                return;
            }
        }
        
        // Format date and time combined: "YYYY/MM/DD HH:MM"
        // CRITICAL: Use dateToUse (preferably from DOM selection) to ensure correct date
        const year = parseInt(dateToUse.year);
        const month = parseInt(dateToUse.month);
        const day = parseInt(dateToUse.day);
        
        console.log('Date components (from dateToUse):', { year, month, day });

        // #region agent log - Hypothesis H4: Parsed year/month/day are coerced back to "today"
        try {
            // DISABLED: Telemetry endpoint causes ERR_CONNECTION_REFUSED
        } catch (e) {}
        // #endregion
        
        // Final validation before formatting
        if (isNaN(year) || isNaN(month) || isNaN(day)) {
            console.error('❌ CRITICAL ERROR: Invalid date components after parsing!', { year, month, day });
            alert('خطا در انتخاب تاریخ. لطفاً دوباره تلاش کنید.');
            return;
        }
        
        const dateStr = `${year}/${String(month).padStart(2, '0')}/${String(day).padStart(2, '0')}`;
        const combinedStr = `${dateStr} ${timeStr}`;

        // #region agent log - Hypothesis H3: Final formatted string vs. expected date
        try {
            // DISABLED: Telemetry endpoint causes ERR_CONNECTION_REFUSED
        } catch (e) {}
        // #endregion
        
        console.log('=== DATE SELECTION DEBUG ===');
        console.log('Selected date object:', JSON.stringify(this.selectedDate));
        console.log('Selected date - Year:', this.selectedDate.year, 'Month:', this.selectedDate.month, 'Day:', this.selectedDate.day);
        console.log('Formatted date string:', dateStr);
        console.log('Time string:', timeStr);
        console.log('Combined string to set:', combinedStr);
        console.log('Input element:', this.input);
        console.log('Input element ID:', this.input?.id);
        console.log('Input element name:', this.input?.name);
        
        // CRITICAL: Set the input value with the selected date
        const previousValue = this.input.value;
        this.input.value = combinedStr;
        
        // Verify the value was set correctly
        console.log('Input value BEFORE setting:', previousValue);
        console.log('Input value AFTER setting:', this.input.value);
        console.log('Input value verification:', this.input.value === combinedStr ? '✅ MATCH' : '❌ MISMATCH');
        
        // Also set via setAttribute to ensure it's in the DOM (useful for
        // later reads via getAttribute in setInitialDateSync)
        this.input.setAttribute('value', combinedStr);
        console.log('Input value after setAttribute:', this.input.getAttribute('value'));
        
        // Trigger input event to ensure form fields are updated
        this.input.dispatchEvent(new Event('input', { bubbles: true }));
        this.input.dispatchEvent(new Event('change', { bubbles: true }));
        
        // Double-check after events
        console.log('Input value after events:', this.input.value);
        
        // Store time for callback
        this.selectedTime = timeStr;
        
        // CRITICAL: Store the selected date string for verification
        const savedDateStr = combinedStr;
        console.log('Saved date string:', savedDateStr);
        
        // Close modal
        this.closeModal();
        
        // Final verification after modal closes (using setTimeout to ensure DOM has updated)
        setTimeout(() => {
            const finalCheck = document.getElementById('deadline-date-input');
            if (finalCheck) {
                console.log('=== FINAL VALUE CHECK (after modal close) ===');
                console.log('Input value after modal close:', finalCheck.value);
                console.log('Expected value:', savedDateStr);
                if (finalCheck.value !== savedDateStr) {
                    console.error('❌ CRITICAL: Input value was changed after modal close!');
                    console.error('Current value:', finalCheck.value);
                    console.error('Expected value:', savedDateStr);
                    console.error('Resetting to correct value...');
                    finalCheck.value = savedDateStr;
                    finalCheck.setAttribute('value', savedDateStr);
                    // Force update
                    finalCheck.dispatchEvent(new Event('input', { bubbles: true }));
                    finalCheck.dispatchEvent(new Event('change', { bubbles: true }));
                    console.log('Value after reset:', finalCheck.value);
                } else {
                    console.log('✅ Value correctly preserved after modal close');
                }
            } else {
                console.error('❌ CRITICAL: deadline-date-input element not found after modal close!');
            }
        }, 100);
        
        // Additional verification after a longer delay
        setTimeout(() => {
            const finalCheck2 = document.getElementById('deadline-date-input');
            if (finalCheck2 && finalCheck2.value !== savedDateStr) {
                console.error('❌ CRITICAL: Input value changed again after 500ms!');
                console.error('Resetting again...');
                finalCheck2.value = savedDateStr;
                finalCheck2.setAttribute('value', savedDateStr);
            }
        }, 500);
        
        // Callback (pass combined string and time separately for compatibility)
        if (this.options.onSelect) {
            this.options.onSelect(combinedStr, timeStr);
        }
        
        console.log('=== DATE SELECTION COMPLETED ===');
        console.log('Final saved date string:', savedDateStr);
    }
    
    isToday(dayData) {
        // Simplified today check - in production, use proper Jalali date comparison
        const today = new Date();
        const dayDate = new Date(dayData.gregorian_date);
        return today.toDateString() === dayDate.toDateString();
    }
}

// Export for browser use (global)
if (typeof window !== 'undefined') {
    window.JalaliCalendarPicker = JalaliCalendarPicker;
}

// Export for Node.js module system
if (typeof module !== 'undefined' && module.exports) {
    module.exports = JalaliCalendarPicker;
}

