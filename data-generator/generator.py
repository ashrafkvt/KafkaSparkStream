# data-generator/generator.py
import json
import os
import random
import time
from datetime import datetime
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

# Configuration from environment variables
KAFKA_BROKER = os.environ.get('KAFKA_BROKER', 'localhost:9092')
TOPIC_NAME = os.environ.get('TOPIC_NAME', 'raw-data')
MESSAGES_PER_SECOND = int(os.environ.get('MESSAGES_PER_SECOND', 10))

# Create a Kafka producer with retry logic
def create_kafka_producer(max_retries=10, retry_interval=5):
    retries = 0
    while retries < max_retries:
        try:
            producer = KafkaProducer(
                bootstrap_servers=[KAFKA_BROKER],
                value_serializer=lambda x: json.dumps(x).encode('utf-8'),
                acks='all',  # Wait for all replicas
                retries=3,   # Retry sending messages
                request_timeout_ms=10000  # Increase timeout for broker connection
            )
            print(f"Successfully connected to Kafka at {KAFKA_BROKER}")
            return producer
        except NoBrokersAvailable:
            retries += 1
            print(f"Failed to connect to Kafka. Retrying in {retry_interval} seconds ({retries}/{max_retries})...")
            time.sleep(retry_interval)
    
    raise Exception(f"Failed to connect to Kafka after {max_retries} attempts")

# Sample data generation - simulating IoT sensor data
def generate_sensor_data():
    device_types = ['temperature', 'humidity', 'pressure', 'motion', 'light']
    locations = ['room1', 'room2', 'kitchen', 'living_room', 'bathroom', 'outdoor']
    
    return {
        'device_id': f"sensor_{random.randint(1, 100)}",
        'device_type': random.choice(device_types),
        'location': random.choice(locations),
        'value': round(random.uniform(0, 100), 2),
        'battery_level': random.uniform(0, 100),
        'timestamp': datetime.now().isoformat()
    }

# Create Kafka topic function
def ensure_topic_exists(producer, topic_name):
    # Check if the topic exists by trying to get metadata 
    # (the admin client is more complex and might not be necessary for this example)
    try:
        # This will throw an exception if the topic doesn't exist
        producer.partitions_for(topic_name)
        print(f"Topic {topic_name} already exists")
    except Exception as e:
        print(f"Topic {topic_name} might not exist: {e}")
        print(f"Note: With Kafka's auto.create.topics.enable=true (default), topics will be created automatically")

# Main loop to generate and send data
def main():
    print(f"Starting data generator, connecting to Kafka at {KAFKA_BROKER}, topic: {TOPIC_NAME}")
    
    # Wait to ensure Kafka is ready
    print("Waiting for Kafka to be ready...")
    time.sleep(15)
    
    # Create producer with retry logic
    producer = create_kafka_producer()
    
    # Ensure topic exists
    ensure_topic_exists(producer, TOPIC_NAME)
    
    # Start sending messages
    print(f"Sending messages at rate of {MESSAGES_PER_SECOND} per second")
    message_count = 0
    
    while True:
        try:
            # Generate sensor data
            sensor_data = generate_sensor_data()
            
            # Send to Kafka
            future = producer.send(TOPIC_NAME, value=sensor_data)
            # Optional: Wait for the message to be sent
            # result = future.get(timeout=10)
            
            message_count += 1
            if message_count % 100 == 0:
                print(f"Sent {message_count} messages so far")
            else:
                print(f"Sent: {sensor_data['device_id']} - {sensor_data['value']}")
            
            # Sleep to control message rate
            time.sleep(1 / MESSAGES_PER_SECOND)

        except Exception as e:
            print(f"Error sending message: {e}")
            time.sleep(5)  # Wait before retrying

if __name__ == "__main__":
    main()
