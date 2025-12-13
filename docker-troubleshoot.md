# Docker Troubleshooting Guide

## 🚨 Docker Registry Access Issues

If you're getting 403 Forbidden errors when pulling Docker images, try these solutions:

### Solution 1: Use a Different Python Image

The current Dockerfile uses `python:3.11`. If this doesn't work, try:

```dockerfile
# Alternative 1: Use a different Python version
FROM python:3.10

# Alternative 2: Use a different registry
FROM registry.hub.docker.com/library/python:3.11

# Alternative 3: Use a minimal image
FROM python:3.11-alpine3.18
```

### Solution 2: Configure Docker to Use Alternative Registries

1. **Create or edit `~/.docker/config.json`:**
```json
{
  "registry-mirrors": [
    "https://mirror.gcr.io",
    "https://registry-1.docker.io"
  ]
}
```

2. **Restart Docker Desktop**

### Solution 3: Use Docker Buildx with Different Platform

```bash
docker buildx build --platform linux/amd64 -t pticket .
```

### Solution 4: Manual Image Pull

Try pulling the image manually first:
```bash
docker pull python:3.11
```

### Solution 5: Use a Local Python Installation

If all else fails, you can run Django locally without Docker:

1. **Install Python 3.11 locally**
2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Run Django:**
   ```bash
   python manage.py runserver
   ```

## 🔧 Quick Fixes

### If Docker Compose Fails:

1. **Try building without cache:**
   ```bash
   docker compose build --no-cache
   ```

2. **Try with different compose file:**
   ```bash
   docker compose -f docker-compose.dev.yml up --build
   ```

3. **Check Docker status:**
   ```bash
   docker info
   docker version
   ```

### Alternative Dockerfile

If the main Dockerfile doesn't work, try this alternative:

```dockerfile
# Alternative Dockerfile
FROM ubuntu:22.04

# Install Python
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-pip \
    python3.11-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Create directories
RUN mkdir -p /app/static /app/media

# Expose port
EXPOSE 8000

# Run Django
CMD ["python3", "manage.py", "runserver", "0.0.0.0:8000"]
```

## 📞 Getting Help

If none of these solutions work:

1. **Check your internet connection**
2. **Try using a VPN**
3. **Contact Docker support**: https://hub.docker.com/support/contact/
4. **Use local development** (see Solution 5 above)

## 🎯 Recommended Next Steps

1. Try the updated Dockerfile with `python:3.11`
2. If that fails, try the alternative Dockerfile
3. If both fail, use local development
4. Report the issue to Docker support 