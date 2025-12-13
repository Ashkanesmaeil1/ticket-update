# Local Development Setup (Without Docker)

Since Docker registry access is having issues, here's how to run the project locally:

## 🚀 Quick Start

### 1. Install Python 3.11
Download and install Python 3.11 from: https://www.python.org/downloads/

### 2. Create Virtual Environment
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run Migrations
```bash
python manage.py migrate
```

### 5. Create Superuser (Optional)
```bash
python manage.py createsuperuser
```

### 6. Run Development Server
```bash
python manage.py runserver
```

### 7. Access Application
Open your browser and go to: http://localhost:8000

## 🔧 Development Commands

```bash
# Make migrations
python manage.py makemigrations

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Collect static files
python manage.py collectstatic --noinput

# Run tests
python manage.py test

# Access Django shell
python manage.py shell
```

## 📁 Project Structure

```
pTicket/
├── manage.py              # Django management script
├── requirements.txt       # Python dependencies
├── ticket_system/        # Main Django project
├── tickets/              # Main app
├── templates/            # HTML templates
├── static/               # Static files
├── media/                # User uploaded files
└── db.sqlite3           # SQLite database
```

## ⚙️ Environment Variables

Create a `.env` file in the project root:

```env
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1
```

## 🛠️ Troubleshooting

### Common Issues:

1. **Python not found**
   - Make sure Python 3.11 is installed
   - Check PATH environment variable

2. **Package installation fails**
   - Upgrade pip: `pip install --upgrade pip`
   - Try: `pip install -r requirements.txt --force-reinstall`

3. **Database errors**
   - Delete `db.sqlite3` and run migrations again
   - Run: `python manage.py migrate`

4. **Static files not loading**
   - Run: `python manage.py collectstatic --noinput`

## 🎯 Advantages of Local Development

- ✅ No Docker registry issues
- ✅ Faster startup time
- ✅ Direct access to files
- ✅ Easier debugging
- ✅ No container overhead

## 🔄 Switching Back to Docker

Once Docker registry issues are resolved, you can switch back to Docker:

```bash
# Try the main Dockerfile
docker compose up --build

# Or try the alternative
docker compose -f docker-compose.alternative.yml up --build
```

## 📞 Getting Help

If you encounter issues:

1. Check Python version: `python --version`
2. Check pip version: `pip --version`
3. Verify virtual environment is activated
4. Check if all dependencies are installed: `pip list` 