# spark-processor/Dockerfile
FROM bitnami/spark:3.4

USER root

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install pyspark==3.4.0 psycopg2-binary==2.9.5

# Copy application code
COPY processor.py /app/processor.py

# Set the entry point
CMD ["spark-submit", "--master", "spark://spark-master:7077", "/app/processor.py"]