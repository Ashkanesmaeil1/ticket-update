@echo off
echo 🚀 Setting up Django Ticket System with Docker...

REM Check if Docker is installed
docker --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker is not installed. Please install Docker Desktop first.
    pause
    exit /b 1
)

REM Check if Docker Compose is installed
docker-compose --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker Compose is not installed. Please install Docker Compose first.
    pause
    exit /b 1
)

REM Create .env file if it doesn't exist
if not exist .env (
    echo 📝 Creating .env file from env.example...
    copy env.example .env
    echo ✅ .env file created successfully!
) else (
    echo ✅ .env file already exists
)

REM Build and start the containers
echo 🔨 Building Docker containers...
docker-compose -f docker-compose.dev.yml build

echo 🚀 Starting development environment...
docker-compose -f docker-compose.dev.yml up -d

REM Wait for the container to be ready
echo ⏳ Waiting for the application to start...
timeout /t 10 /nobreak >nul

REM Run migrations
echo 🗄️ Running database migrations...
docker-compose -f docker-compose.dev.yml exec web python manage.py migrate

REM Create superuser if needed
set /p create_superuser="👤 Do you want to create a superuser? (y/n): "
if /i "%create_superuser%"=="y" (
    docker-compose -f docker-compose.dev.yml exec web python manage.py createsuperuser
)

REM Collect static files
echo 📦 Collecting static files...
docker-compose -f docker-compose.dev.yml exec web python manage.py collectstatic --noinput

echo ✅ Setup complete!
echo.
echo 🌐 Your Django application is now running at:
echo    http://localhost:8000
echo.
echo 📋 Useful commands:
echo    - View logs: docker-compose -f docker-compose.dev.yml logs -f
echo    - Stop containers: docker-compose -f docker-compose.dev.yml down
echo    - Restart containers: docker-compose -f docker-compose.dev.yml restart
echo    - Access shell: docker-compose -f docker-compose.dev.yml exec web bash
echo    - Run migrations: docker-compose -f docker-compose.dev.yml exec web python manage.py migrate
echo    - Create superuser: docker-compose -f docker-compose.dev.yml exec web python manage.py createsuperuser
echo.
echo 🔄 Hot reload is enabled - your changes will be reflected automatically!
pause 