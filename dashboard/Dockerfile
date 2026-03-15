FROM python:3.11-slim

# Set environment variables to ensure Python output is logged and not buffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0

WORKDIR /app

# Install system dependencies required for some Python packages and healthcheck
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file first to leverage Docker cache
# This assumes the build context is the 'dashboard' directory or 
# that requirements.txt is present in the directory with the Dockerfile
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Streamlit uses port 8501 by default
EXPOSE 8501

# Healthcheck to monitor the status of the Streamlit application
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

# Execute the Streamlit application
# We assume the main entry point is app.py
ENTRYPOINT ["streamlit", "run", "app.py"]