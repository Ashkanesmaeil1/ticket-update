// Admin JavaScript for User management
(function ($) {
    'use strict';

    // Department choices for different roles
    const EMPLOYEE_DEPARTMENTS = [
        ['', '---------'],
        ['اداری', 'اداری'],
        ['برنامه‌ریزی و کنترل پروژه', 'برنامه‌ریزی و کنترل پروژه'],
        ['تدارکات', 'تدارکات'],
        ['کنترل کیفیت', 'کنترل کیفیت'],
        ['قراردادها', 'قراردادها'],
        ['منابع انسانی', 'منابع انسانی'],
        ['مناقصات', 'مناقصات'],
        ['مهندسی و فنی', 'مهندسی و فنی'],
        ['MTO', 'MTO'],
        ['پروژه‌ها', 'پروژه‌ها'],
        ['فیلتر فروش', 'فیلتر فروش'],
        ['سایر', 'سایر']
    ];

    const TECHNICIAN_DEPARTMENTS = [
        ['', '---------'],
        ['پشتیبانی فنی', 'پشتیبانی فنی'],
        ['امنیت اطلاعات', 'امنیت اطلاعات'],
        ['توسعه نرم افزار', 'توسعه نرم افزار'],
        ['مدیریت پایگاه داده', 'مدیریت پایگاه داده'],
        ['مدیریت سیستم ها', 'مدیریت سیستم ها'],
        ['مدیریت شبکه', 'مدیریت شبکه'],
        ['سایر', 'سایر']
    ];

    function updateDepartmentChoices() {
        const roleField = $('#id_role');
        const departmentField = $('#id_department');
        const departmentRoleField = $('#id_department_role');

        if (!roleField.length || !departmentField.length) return;

        const selectedRole = roleField.val();

        // CRITICAL: Check if department field is a queryset-based field (ForeignKey)
        // If it has options with numeric IDs, it's a queryset field - don't override it
        const isQuerysetField = departmentField.find('option[value!=""]').length > 0 &&
            departmentField.find('option[value!=""]').first().val().match(/^\d+$/);

        // Update department choices based on role
        // CRITICAL: For employees with queryset-based fields, preserve the server-side filtered queryset
        // Only update for technicians (they use hardcoded departments) or if it's not a queryset field
        if (selectedRole === 'technician') {
            updateSelectOptions(departmentField, TECHNICIAN_DEPARTMENTS);
        } else if (selectedRole === 'employee' && isQuerysetField) {
            // For employees with queryset fields, DON'T override the server-side queryset
            // The server-side form already filters departments based on department_role
            // Just ensure the field is enabled - the server has already filtered it correctly
            departmentField.prop('disabled', false);
            departmentField.css('opacity', '1');
            // Don't call updateSelectOptions - preserve server-side filtering
        } else if (selectedRole === 'employee' && !isQuerysetField) {
            // Fallback for non-queryset fields (shouldn't happen, but just in case)
            updateSelectOptions(departmentField, EMPLOYEE_DEPARTMENTS);
        }

        // Handle department_role field visibility and department field disabling
        if (departmentRoleField.length) {
            if (selectedRole === 'employee') {
                // Show department_role field for employees
                departmentRoleField.closest('.form-row').show();
                toggleDepartmentField();
            } else {
                // Hide department_role field for non-employees
                departmentRoleField.closest('.form-row').hide();
                departmentField.prop('disabled', false);
                departmentField.css('opacity', '1');
            }
        }
    }

    function updateSelectOptions(selectElement, options) {
        selectElement.empty();
        options.forEach(function (option) {
            selectElement.append(new Option(option[1], option[0]));
        });
    }

    function toggleDepartmentField() {
        const departmentRoleInputs = $('input[name="department_role"]');
        const departmentField = $('#id_department');

        if (!departmentField.length) return;

        let selectedRole = '';
        departmentRoleInputs.each(function () {
            if ($(this).is(':checked')) {
                selectedRole = $(this).val();
            }
        });

        console.log('Department role selected:', selectedRole); // Debug log

        if (selectedRole === 'manager') {
            departmentField.prop('disabled', true);
            departmentField.val('');
            departmentField.css('opacity', '0.5');
            console.log('Department field disabled for manager'); // Debug log
        } else {
            departmentField.prop('disabled', false);
            departmentField.css('opacity', '1');
            console.log('Department field enabled'); // Debug log
        }
    }

    // Initialize when document is ready
    $(document).ready(function () {
        console.log('Admin JS loaded'); // Debug log

        // Wait a moment for the form to fully render, then initialize
        setTimeout(function () {
            console.log('Initializing department choices...'); // Debug log
            updateDepartmentChoices();
            toggleDepartmentField();
        }, 100);

        // Handle role field changes
        $('#id_role').on('change', function () {
            console.log('Role changed to:', $(this).val()); // Debug log
            updateDepartmentChoices();
        });

        // Handle department_role field changes
        $('input[name="department_role"]').on('change', function () {
            console.log('Department role changed to:', $(this).val()); // Debug log
            toggleDepartmentField();

            // Filter departments if Team Lead is selected (for creation form)
            const selectedRole = $(this).val();
            const departmentField = $('#id_department');

            // Check if department field is a queryset-based field (ForeignKey)
            const isQuerysetField = departmentField.length > 0 &&
                departmentField.find('option[value!=""]').length > 0 &&
                departmentField.find('option[value!=""]').first().val().match(/^\d+$/);

            if ((selectedRole === 'senior' || selectedRole === 'manager') && isQuerysetField) {
                // Get current user ID if editing (from form action URL or hidden field)
                const formAction = $('form').attr('action') || window.location.pathname;
                const userIdMatch = formAction.match(/\/edit-employee\/(\d+)\//);
                const userId = userIdMatch ? userIdMatch[1] : null;

                // Build API URL (use relative path that matches Django URL pattern)
                let apiUrl = '/api/departments/without-team-lead/';
                if (userId) {
                    apiUrl += '?user_id=' + userId;
                }

                // Store current value before updating
                const currentValue = departmentField.val();

                // Fetch filtered departments via AJAX
                $.ajax({
                    url: apiUrl,
                    method: 'GET',
                    success: function (data) {
                        if (data.success && data.departments) {
                            // Clear and repopulate department dropdown
                            departmentField.empty();
                            departmentField.append($('<option>', {
                                value: '',
                                text: '---------'
                            }));

                            data.departments.forEach(function (dept) {
                                const option = $('<option>', {
                                    value: dept.id,
                                    text: dept.name
                                });
                                if (dept.id == currentValue) {
                                    option.prop('selected', true);
                                }
                                departmentField.append(option);
                            });

                            console.log('Department dropdown filtered for Team Lead');
                        }
                    },
                    error: function (xhr, status, error) {
                        console.error('Error fetching filtered departments:', error);
                    }
                });
            } else if (selectedRole !== 'senior' && selectedRole !== 'manager' && isQuerysetField) {
                // Not a Team Lead - reload all departments
                const currentValue = departmentField.val();

                $.ajax({
                    url: '/api/departments/all-employee/',
                    method: 'GET',
                    success: function (data) {
                        if (data.success && data.departments) {
                            // Clear and repopulate department dropdown with all departments
                            departmentField.empty();
                            departmentField.append($('<option>', {
                                value: '',
                                text: '---------'
                            }));

                            data.departments.forEach(function (dept) {
                                const option = $('<option>', {
                                    value: dept.id,
                                    text: dept.name
                                });
                                if (dept.id == currentValue) {
                                    option.prop('selected', true);
                                }
                                departmentField.append(option);
                            });

                            console.log('Department dropdown restored to show all departments');
                        }
                    },
                    error: function (xhr, status, error) {
                        console.error('Error fetching all departments:', error);
                    }
                });
            }
        });

        // Also handle when the page loads with existing data (for edit forms)
        $(window).on('load', function () {
            console.log('Window loaded, updating choices...'); // Debug log
            updateDepartmentChoices();
            toggleDepartmentField();
        });

        // Handle form submission to ensure department is cleared for managers
        $('form').on('submit', function () {
            const departmentRoleInputs = $('input[name="department_role"]');
            const departmentField = $('#id_department');

            if (departmentRoleInputs.length && departmentField.length) {
                let selectedRole = '';
                departmentRoleInputs.each(function () {
                    if ($(this).is(':checked')) {
                        selectedRole = $(this).val();
                    }
                });

                if (selectedRole === 'manager') {
                    departmentField.val('');
                }
            }
        });
    });

})(django.jQuery); 