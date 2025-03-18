# spark-processor/processor.py
import os
import json
import time
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    from_json, col, window, avg, max, min, count
)
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, TimestampType
)

# Configuration
KAFKA_BROKER = os.environ.get('KAFKA_BROKER', 'kafka:29092')
KAFKA_TOPIC = os.environ.get('KAFKA_TOPIC', 'raw-data')
POSTGRES_URL = os.environ.get(
    'POSTGRES_URL', 'jdbc:postgresql://postgres:5432/dataengineering')
POSTGRES_PROPERTIES = {
    'user': os.environ.get('POSTGRES_USER', 'postgres'),
    'password': os.environ.get('POSTGRES_PASSWORD', 'postgres'),
    'driver': 'org.postgresql.Driver'
}

def create_spark_session():
    print("Initializing Spark session...")
    
    # Wait for services to be ready
    time.sleep(20)
    
    # Initialize Spark Session with Kafka and PostgreSQL dependencies
    return SparkSession.builder \
        .appName("IoT Sensor Data Processor") \
        .config("spark.jars.packages", 
                "org.apache.spark:spark-sql-kafka-0-10_2.12:3.4.0,"
                "org.postgresql:postgresql:42.5.1") \
        .config("spark.executor.memory", "1g") \
        .config("spark.sql.streaming.checkpointLocation", "/tmp/checkpoints") \
        .getOrCreate()

def process_streaming_data():
    spark = create_spark_session()
    
    # Set log level
    spark.sparkContext.setLogLevel("WARN")
    print("Spark session initialized")

    # Define schema for the incoming data
    schema = StructType([
        StructField("device_id", StringType(), True),
        StructField("device_type", StringType(), True),
        StructField("location", StringType(), True),
        StructField("value", DoubleType(), True),
        StructField("battery_level", DoubleType(), True),
        StructField("timestamp", StringType(), True)
    ])

    print(f"Connecting to Kafka broker: {KAFKA_BROKER}, topic: {KAFKA_TOPIC}")
    
    # Read streaming data from Kafka
    kafka_stream = spark \
        .readStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", KAFKA_BROKER) \
        .option("subscribe", KAFKA_TOPIC) \
        .option("startingOffsets", "earliest") \
        .option("failOnDataLoss", "false") \
        .load()
    
    print("Connected to Kafka stream")

    # Parse the JSON data
    parsed_stream = kafka_stream \
        .selectExpr("CAST(value AS STRING)") \
        .select(from_json(col("value"), schema).alias("data")) \
        .select("data.*") \
        .withColumn("timestamp", col("timestamp").cast(TimestampType()))

    # Create temporary view for raw data
    parsed_stream.createOrReplaceTempView("raw_sensor_data")
    
    # Process the data - Compute aggregates by device type and location
    aggregated_data = parsed_stream \
        .withWatermark("timestamp", "1 minute") \
        .groupBy(
            window(col("timestamp"), "1 minute"),
            col("device_type"),
            col("location")
        ) \
        .agg(
            avg("value").alias("avg_value"),
            min("value").alias("min_value"),
            max("value").alias("max_value"),
            avg("battery_level").alias("avg_battery"),
            count("*").alias("reading_count")
        )

    print("Starting write streams to PostgreSQL...")
    
    # Output aggregated data to PostgreSQL
    aggregated_query = aggregated_data \
        .writeStream \
        .foreachBatch(
            lambda batch_df, batch_id: write_to_postgres(batch_df, batch_id, "sensor_aggregates")
        ) \
        .outputMode("update") \
        .option("checkpointLocation", "/tmp/checkpoints_agg") \
        .start()

    # Write raw data to PostgreSQL
    raw_query = parsed_stream \
        .writeStream \
        .foreachBatch(
            lambda batch_df, batch_id: write_to_postgres(batch_df, batch_id, "sensor_data")
        ) \
        .outputMode("append") \
        .option("checkpointLocation", "/tmp/checkpoints_raw") \
        .start()

    print("All streams started. Waiting for termination...")
    
    # Wait for termination
    spark.streams.awaitAnyTermination()

def write_to_postgres(batch_df, batch_id, table_name):
    """Write batch DataFrame to PostgreSQL with error handling"""
    try:
        if not batch_df.isEmpty():
            print(f"Writing batch {batch_id} to {table_name}")
            batch_df.write \
                .jdbc(
                    url=POSTGRES_URL,
                    table=table_name,
                    mode="append",
                    properties=POSTGRES_PROPERTIES
                )
            print(f"Successfully wrote batch {batch_id} to {table_name}")
        else:
            print(f"Batch {batch_id} is empty, skipping write to {table_name}")
    except Exception as e:
        print(f"Error writing batch {batch_id} to {table_name}: {e}")

if __name__ == "__main__":
    try:
        process_streaming_data()
    except Exception as e:
        print(f"Error in main processing: {e}")