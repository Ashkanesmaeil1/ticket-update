# Docker Development Setup for Django Ticket System

This guide will help you set up and run the Django Ticket System locally using Docker Compose with hot reload support.

## 🚀 Quick Start

### Prerequisites
- Docker Desktop installed and running
- Docker Compose installed
- Git (to clone the repository)

### 1. Initial Setup

```bash
# Clone the repository (if not already done)
git clone <repository-url>
cd pticket

# Copy environment variables
cp env.example .env

# Run the setup script (Linux/Mac)
chmod +x docker-setup.sh
./docker-setup.sh

# Or run manually (Windows)
docker-compose -f docker-compose.dev.yml build
docker-compose -f docker-compose.dev.yml up -d
```

### 2. Database Setup

```bash
# Run migrations
docker-compose -f docker-compose.dev.yml exec web python manage.py migrate

# Create superuser (optional)
docker-compose -f docker-compose.dev.yml exec web python manage.py createsuperuser

# Collect static files
docker-compose -f docker-compose.dev.yml exec web python manage.py collectstatic --noinput
```

### 3. Access the Application

- **Main Application**: http://localhost:8000
- **Admin Panel**: http://localhost:8000/admin/

## 📋 Common Commands

### Development Commands

```bash
# Start development environment (with hot reload)
docker-compose -f docker-compose.dev.yml up

# Start in background
docker-compose -f docker-compose.dev.yml up -d

# Stop containers
docker-compose -f docker-compose.dev.yml down

# View logs
docker-compose -f docker-compose.dev.yml logs -f

# Restart containers
docker-compose -f docker-compose.dev.yml restart

# Rebuild containers
docker-compose -f docker-compose.dev.yml build --no-cache
```

### Django Management Commands

```bash
# Access Django shell
docker-compose -f docker-compose.dev.yml exec web python manage.py shell

# Run migrations
docker-compose -f docker-compose.dev.yml exec web python manage.py migrate

# Create migrations
docker-compose -f docker-compose.dev.yml exec web python manage.py makemigrations

# Create superuser
docker-compose -f docker-compose.dev.yml exec web python manage.py createsuperuser

# Collect static files
docker-compose -f docker-compose.dev.yml exec web python manage.py collectstatic --noinput

# Run tests
docker-compose -f docker-compose.dev.yml exec web python manage.py test

# Access bash shell
docker-compose -f docker-compose.dev.yml exec web bash
```

## 🔧 Configuration Files Explained

### docker-compose.dev.yml
This is the main development configuration file:

- **Hot Reload**: Uses `python manage.py runserver` without `--noreload` flag
- **Volume Mounting**: Maps your local code to `/app` in the container
- **Port Mapping**: Exposes port 8000 for web access
- **Environment Variables**: Sets development-specific variables
- **Volumes**: Persistent storage for static and media files

### Dockerfile
The container image definition:

- **Base Image**: Python 3.11-slim (lightweight)
- **Dependencies**: Installs system and Python packages
- **Static Files**: Collects static files during build
- **Port**: Exposes port 8000

### .env File
Environment variables for development:

```env
DEBUG=True
SECRET_KEY=dev-secret-key-change-in-production
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0
DJANGO_SETTINGS_MODULE=ticket_system.settings
```

## 🔄 Hot Reload

The development setup includes hot reload functionality:

- **Code Changes**: Any changes to Python files will automatically restart the server
- **Template Changes**: Template changes are reflected immediately
- **Static Files**: Static file changes require manual collection or restart

## 🗄️ Database

The development setup uses SQLite by default:

- **Database File**: `db.sqlite3` (persisted in volume)
- **Migrations**: Run automatically on startup
- **Data Persistence**: Data persists between container restarts

## 📁 File Structure

```
pticket/
├── docker-compose.dev.yml    # Development Docker Compose config
├── docker-compose.yml        # Production Docker Compose config
├── Dockerfile               # Container image definition
├── .env                     # Environment variables (create from env.example)
├── requirements.txt         # Python dependencies
├── manage.py               # Django management script
├── ticket_system/          # Django project settings
├── tickets/                # Django app
├── templates/              # HTML templates
├── static/                 # Static files
└── media/                  # User uploaded files
```

## 🐛 Troubleshooting

### Common Issues

1. **Port 8000 already in use**
   ```bash
   # Check what's using the port
   netstat -ano | findstr :8000
   # Or change the port in docker-compose.dev.yml
   ```

2. **Permission denied errors**
   ```bash
   # On Linux/Mac, fix file permissions
   sudo chown -R $USER:$USER .
   ```

3. **Container won't start**
   ```bash
   # Check logs
   docker-compose -f docker-compose.dev.yml logs
   
   # Rebuild containers
   docker-compose -f docker-compose.dev.yml build --no-cache
   ```

4. **Database issues**
   ```bash
   # Reset database
   docker-compose -f docker-compose.dev.yml exec web python manage.py flush
   
   # Or delete and recreate
   rm db.sqlite3
   docker-compose -f docker-compose.dev.yml exec web python manage.py migrate
   ```

### Debug Commands

```bash
# Check container status
docker-compose -f docker-compose.dev.yml ps

# Check container logs
docker-compose -f docker-compose.dev.yml logs web

# Access container shell
docker-compose -f docker-compose.dev.yml exec web bash

# Check Django settings
docker-compose -f docker-compose.dev.yml exec web python manage.py check
```

## 🚀 Production Setup

For production deployment, use the main `docker-compose.yml` file:

```bash
# Build and start production environment
docker-compose up --build -d

# View production logs
docker-compose logs -f
```

## 📚 Additional Resources

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Django Documentation](https://docs.djangoproject.com/)

## 🤝 Contributing

When making changes:

1. Make your code changes
2. Test locally using Docker
3. Run tests: `docker-compose -f docker-compose.dev.yml exec web python manage.py test`
4. Commit your changes

The hot reload feature means most changes will be reflected immediately without restarting the container! 