FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire application
COPY . .

# Create necessary directories
RUN mkdir -p content/assets db

# Expose Flask port
EXPOSE 5000

# Copy startup script
COPY start.sh /start.sh
RUN chmod +x /start.sh

# Run both services
CMD ["/start.sh"]