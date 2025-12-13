@echo off
echo 🚀 Running Private Reply migration using Docker...

REM Build the Docker image
echo 📦 Building Docker image...
docker build -t pticket .

REM Run the migration
echo 🔄 Running migration...
docker run --rm -v %cd%:/app pticket python manage.py migrate

echo ✅ Migration completed!
echo 🎉 Private Reply feature is now available!
pause 