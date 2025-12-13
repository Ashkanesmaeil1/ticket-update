#!/bin/bash

# Docker Setup Script for Django Ticket System
# This script sets up the development environment using Docker Compose

set -e

echo "🚀 Setting up Django Ticket System with Docker..."

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file from env.example..."
    cp env.example .env
    echo "✅ .env file created successfully!"
else
    echo "✅ .env file already exists"
fi

# Build and start the containers
echo "🔨 Building Docker containers..."
docker-compose -f docker-compose.dev.yml build

echo "🚀 Starting development environment..."
docker-compose -f docker-compose.dev.yml up -d

# Wait for the container to be ready
echo "⏳ Waiting for the application to start..."
sleep 10

# Run migrations
echo "🗄️ Running database migrations..."
docker-compose -f docker-compose.dev.yml exec web python manage.py migrate

# Create superuser if needed
echo "👤 Do you want to create a superuser? (y/n)"
read -r create_superuser
if [[ $create_superuser =~ ^[Yy]$ ]]; then
    docker-compose -f docker-compose.dev.yml exec web python manage.py createsuperuser
fi

# Collect static files
echo "📦 Collecting static files..."
docker-compose -f docker-compose.dev.yml exec web python manage.py collectstatic --noinput

echo "✅ Setup complete!"
echo ""
echo "🌐 Your Django application is now running at:"
echo "   http://localhost:8000"
echo ""
echo "📋 Useful commands:"
echo "   - View logs: docker-compose -f docker-compose.dev.yml logs -f"
echo "   - Stop containers: docker-compose -f docker-compose.dev.yml down"
echo "   - Restart containers: docker-compose -f docker-compose.dev.yml restart"
echo "   - Access shell: docker-compose -f docker-compose.dev.yml exec web bash"
echo "   - Run migrations: docker-compose -f docker-compose.dev.yml exec web python manage.py migrate"
echo "   - Create superuser: docker-compose -f docker-compose.dev.yml exec web python manage.py createsuperuser"
echo ""
echo "🔄 Hot reload is enabled - your changes will be reflected automatically!" 