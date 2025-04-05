# api-service/Dockerfile
FROM python:3.10-alpine

WORKDIR /app

# Install necessary packages including PostgreSQL client
RUN apk add --no-cache postgresql-dev gcc python3-dev musl-dev

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .

# Run the application with Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
