#!/bin/bash

echo "🚀 Running Private Reply migration using Docker..."

# Build the Docker image
echo "📦 Building Docker image..."
docker build -t pticket .

# Run the migration
echo "🔄 Running migration..."
docker run --rm -v $(pwd):/app pticket python manage.py migrate

echo "✅ Migration completed!"
echo "🎉 Private Reply feature is now available!" 