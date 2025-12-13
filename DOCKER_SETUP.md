# Docker Setup for pTicket

## ✅ Fixed Issues

1. **Removed obsolete `version` attribute** from docker-compose.yml
2. **Properly defined volumes** in docker-compose.yml
3. **Simplified requirements.txt** to remove unnecessary dependencies
4. **Updated Dockerfile** to use Alpine Linux for better reliability

## 🚀 Quick Start

### 1. Build and start the application
```bash
docker compose up --build
```

### 2. Access the application
- Open your browser and go to: http://localhost:8000

### 3. Run initial setup
```bash
# Run migrations
docker compose exec web python manage.py migrate

# Create superuser
docker compose exec web python manage.py createsuperuser

# Collect static files (if needed)
docker compose exec web python manage.py collectstatic --noinput
```

## 📁 File Structure

### Docker Configuration Files
- `Dockerfile` - Container definition
- `docker-compose.yml` - Main service configuration
- `docker-compose.dev.yml` - Development configuration
- `.dockerignore` - Files to exclude from build

### Environment Files
- `env.example` - Example environment variables
- Copy to `.env` and customize as needed

## 🔧 Docker Commands

### Basic Commands
```bash
# Start application
docker compose up

# Start in background
docker compose up -d

# Stop application
docker compose down

# View logs
docker compose logs -f

# Rebuild (if requirements change)
docker compose build --no-cache
```

### Django Management Commands
```bash
# Run migrations
docker compose exec web python manage.py migrate

# Create superuser
docker compose exec web python manage.py createsuperuser

# Access Django shell
docker compose exec web python manage.py shell

# Make migrations
docker compose exec web python manage.py makemigrations

# Collect static files
docker compose exec web python manage.py collectstatic --noinput

# Run tests
docker compose exec web python manage.py test
```

## 🗂️ Volume Configuration

### Code Changes
- **Host**: `./` (project directory)
- **Container**: `/app`
- **Behavior**: Live reload - changes are reflected immediately

### Static Files
- **Volume**: `static_volume`
- **Container Path**: `/app/static`
- **Purpose**: Persistent static file storage

### Media Files
- **Volume**: `media_volume`
- **Container Path**: `/app/media`
- **Purpose**: Persistent media file storage

### Database
- **Type**: SQLite
- **Location**: `./db.sqlite3` (project root)
- **Behavior**: Persisted in project directory

## ⚙️ Environment Variables

### Default Configuration
```env
DEBUG=True
SECRET_KEY=dev-secret-key-change-in-production
ALLOWED_HOSTS=localhost,127.0.0.1
```

### Customization
1. Copy `env.example` to `.env`
2. Edit `.env` file with your settings
3. Restart containers: `docker compose down && docker compose up`

## 🔍 Troubleshooting

### Common Issues

1. **Port 8000 already in use**
   ```bash
   # Check what's using port 8000
   netstat -ano | findstr :8000
   # Or change port in docker-compose.yml
   ```

2. **Permission issues**
   ```bash
   # Check container status
   docker compose ps
   # View logs
   docker compose logs web
   ```

3. **Database issues**
   ```bash
   # Reset database
   docker compose exec web python manage.py flush
   # Or delete db.sqlite3 and run migrations
   ```

4. **Static files not loading**
   ```bash
   # Collect static files
   docker compose exec web python manage.py collectstatic --noinput
   ```

### Development Workflow

1. **Start development server**
   ```bash
   docker compose up
   ```

2. **Make code changes**
   - Files are mounted, changes are reflected immediately
   - No need to rebuild unless you change requirements.txt

3. **Run Django commands as needed**
   ```bash
   docker compose exec web python manage.py <command>
   ```

4. **View logs for debugging**
   ```bash
   docker compose logs -f web
   ```

## 🛡️ Security Notes

- Change `SECRET_KEY` in production
- Set `DEBUG=False` in production
- Configure proper `ALLOWED_HOSTS` for production
- Use environment variables for sensitive data

## 📦 What's Included

### Services
- **Django Application**: Web server with SQLite database
- **Static Files**: Served by Django development server
- **Media Files**: Stored in Docker volume

### Features
- ✅ Live code reloading
- ✅ SQLite database (no external dependencies)
- ✅ Volume persistence for static/media files
- ✅ Easy Django management commands
- ✅ Development-friendly configuration
- ✅ Minimal resource usage

## 🎯 Summary

Your Docker setup is now:
- **Simple**: Single service with SQLite
- **Fast**: Alpine Linux base image
- **Reliable**: Proper volume definitions
- **Development-friendly**: Live code reloading
- **Easy to use**: Standard Docker Compose commands

Everything should work perfectly now! 🚀 