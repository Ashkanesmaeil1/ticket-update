# pTicket - Persian Ticket Management System

A Django-based ticket management system with full Persian (Farsi) localization and RTL support.

## Features

### Core Functionality
- **Multi-role System**: Employee, Technician, and IT Manager roles
- **Ticket Management**: Create, update, delete, and track tickets
- **File Attachments**: Support for ticket and reply attachments
- **Status Tracking**: Multiple ticket statuses (Open, In Progress, Waiting for Employee, Completed, Closed)
- **Priority Levels**: Low, Medium, High, Urgent priorities
- **Categories**: Hardware, Software, Network, Other categories

### Persian Localization
- **Full RTL Support**: Right-to-left layout for Persian text
- **Persian Calendar**: All dates displayed in Persian (Jalali) calendar
- **Persian Interface**: Complete translation of all UI elements
- **Persian Font**: Vazirmatn font for better Persian text rendering

### Advanced Features
- **Smart Search**: Search tickets by ID, title, description, or user name
- **Role-based Access**: Different views and permissions for each role
- **Dashboard Statistics**: Role-specific dashboard with relevant statistics
- **Responsive Design**: Mobile-friendly interface with Bootstrap 5

### Automatic Workflow
- **Auto Status Change**: When an IT Manager assigns a ticket to a technician, the status automatically changes from "Open" to "In Progress"
- **Smart Assignment**: Only IT Managers can assign tickets to technicians
- **Status Validation**: Employees can only delete their own open tickets

## Installation

### Prerequisites
- Python 3.8+
- Docker (optional)

### Local Development
1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Run migrations: `python manage.py migrate`
4. Create superuser: `python manage.py createsuperuser`
5. Run the server: `python manage.py runserver`

### Docker Setup
1. Build the image: `docker build -t pticket .`
2. Run with Docker Compose: `docker-compose up --build`

## Usage

### For Employees
- Create new tickets with descriptions and attachments
- View and update their own tickets
- Delete their own open tickets
- Receive notifications when tickets are updated

### For Technicians
- View assigned tickets
- Update ticket status and add replies
- Work on tickets assigned by IT Managers

### For IT Managers
- View all tickets in the system
- Assign tickets to technicians (automatically changes status to "In Progress")
- Manage user accounts and roles
- View system statistics
- Update ticket status and priority

## Automatic Status Change Feature

When an IT Manager assigns a ticket to a technician, the system automatically:

1. **Changes Status**: Updates from "Open" to "In Progress"
2. **Shows Notification**: Displays a success message to the IT Manager
3. **Maintains Workflow**: Ensures proper ticket progression

This feature works in both:
- **Form-based Assignment**: When using the ticket detail page form
- **AJAX Assignment**: When using the AJAX status update endpoint

The automatic status change only occurs when:
- The user is an IT Manager
- The assigned user is a Technician
- The current ticket status is "Open"
- This is a new assignment or reassignment to a different technician

## API Endpoints

- `POST /api/tickets/<id>/status/`: Update ticket status and assignment (AJAX)
- `GET /api/tickets/search/`: Search tickets (AJAX)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License.