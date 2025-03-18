# api-service/app.py
from fastapi import FastAPI, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Dict, Any
import psycopg2
import psycopg2.extras
import os
import redis
import json
from pydantic import BaseModel
from datetime import datetime, timedelta

app = FastAPI(title="Sensor Data API", 
              description="API for accessing IoT sensor data processed by Spark",
              version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database connection
def get_db_connection():
    return psycopg2.connect(
        os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@postgres:5432/dataengineering')
    )

# Redis connection
redis_client = redis.Redis.from_url(
    os.environ.get('REDIS_URL', 'redis://redis:6379/0')
)

# Pydantic models for response data
class Sensor(BaseModel):
    device_id: str
    device_type: str
    location: str

class SensorReading(BaseModel):
    id: int
    device_id: str
    device_type: str
    location: str
    value: float
    battery_level: float
    timestamp: datetime
    
    class Config:
        orm_mode = True

class SensorAggregate(BaseModel):
    id: int
    window_start: datetime
    window_end: datetime
    device_type: str
    location: str
    avg_value: float
    min_value: float
    max_value: float
    avg_battery: float
    reading_count: int
    
    class Config:
        orm_mode = True

# Create tables if they don't exist
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Create sensor_data table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS sensor_data (
        id SERIAL PRIMARY KEY,
        device_id VARCHAR(50),
        device_type VARCHAR(50),
        location VARCHAR(50),
        value DOUBLE PRECISION,
        battery_level DOUBLE PRECISION,
        timestamp TIMESTAMP
    )
    ''')
    
    # Create sensor_aggregates table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS sensor_aggregates (
        id SERIAL PRIMARY KEY,
        window_start TIMESTAMP,
        window_end TIMESTAMP,
        device_type VARCHAR(50),
        location VARCHAR(50),
        avg_value DOUBLE PRECISION,
        min_value DOUBLE PRECISION,
        max_value DOUBLE PRECISION,
        avg_battery DOUBLE PRECISION,
        reading_count BIGINT
    )
    ''')
    
    conn.commit()
    cur.close()
    conn.close()

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_db()

# API endpoints
@app.get("/api/sensors", response_model=List[Sensor], tags=["Sensors"])
async def get_sensors():
    """
    Get a list of all unique sensors with their device types and locations.
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    cur.execute('''
    SELECT DISTINCT device_id, device_type, location
    FROM sensor_data
    ORDER BY device_type, location
    ''')
    
    sensors = [dict(row) for row in cur.fetchall()]
    
    cur.close()
    conn.close()
    
    return sensors

@app.get("/api/data/latest", response_model=List[SensorReading], tags=["Sensor Data"])
async def get_latest_data(
    device_type: Optional[str] = Query(None, description="Filter by device type"),
    location: Optional[str] = Query(None, description="Filter by location")
):
    """
    Get the latest sensor readings, optionally filtered by device type and location.
    """
    # Try to get from cache first
    cache_key = f"latest:{device_type}:{location}"
    cached_data = redis_client.get(cache_key)
    
    if cached_data:
        return json.loads(cached_data)
    
    # Otherwise query from database
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    query = '''
    SELECT *
    FROM sensor_data
    WHERE 1=1
    '''
    
    params = []
    
    if device_type:
        query += " AND device_type = %s"
        params.append(device_type)
    
    if location:
        query += " AND location = %s"
        params.append(location)
    
    query += " ORDER BY timestamp DESC LIMIT 100"
    
    cur.execute(query, params)
    
    data = [dict(row) for row in cur.fetchall()]
    
    cur.close()
    conn.close()
    
    # Cache the result
    if data and (device_type or location):
        redis_client.setex(
            cache_key,
            300,  # Cache for 5 minutes
            json.dumps(data, default=str)
        )
    
    return data

@app.get("/api/aggregates", response_model=List[SensorAggregate], tags=["Aggregated Data"])
async def get_aggregates(
    device_type: Optional[str] = Query(None, description="Filter by device type"),
    location: Optional[str] = Query(None, description="Filter by location"),
    hours: int = Query(1, description="Time range in hours", ge=1, le=24)
):
    """
    Get aggregated sensor data over time windows, 
    optionally filtered by device type, location, and time range.
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    query = '''
    SELECT *
    FROM sensor_aggregates
    WHERE window_start >= NOW() - INTERVAL '%s HOURS'
    '''
    
    params = [hours]
    
    if device_type:
        query += " AND device_type = %s"
        params.append(device_type)
    
    if location:
        query += " AND location = %s"
        params.append(location)
    
    query += " ORDER BY window_start DESC"
    
    cur.execute(query, params)
    
    data = [dict(row) for row in cur.fetchall()]
    
    cur.close()
    conn.close()
    
    return data

# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint to verify the API service is running.
    """
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# Stats endpoint for quick metrics
@app.get("/api/stats", tags=["Statistics"])
async def get_stats():
    """
    Get overall statistics about the sensor data.
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    # Get total readings count
    cur.execute("SELECT COUNT(*) as total FROM sensor_data")
    total_readings = cur.fetchone()['total']
    
    # Get device type counts
    cur.execute("""
    SELECT device_type, COUNT(*) as count 
    FROM sensor_data 
    GROUP BY device_type 
    ORDER BY count DESC
    """)
    device_counts = {row['device_type']: row['count'] for row in cur.fetchall()}
    
    # Get location counts
    cur.execute("""
    SELECT location, COUNT(*) as count 
    FROM sensor_data 
    GROUP BY location 
    ORDER BY count DESC
    """)
    location_counts = {row['location']: row['count'] for row in cur.fetchall()}
    
    # Get time range
    cur.execute("""
    SELECT 
        MIN(timestamp) as earliest,
        MAX(timestamp) as latest
    FROM sensor_data
    """)
    time_range = cur.fetchone()
    
    cur.close()
    conn.close()
    
    return {
        "total_readings": total_readings,
        "device_type_distribution": device_counts,
        "location_distribution": location_counts,
        "time_range": {
            "earliest": time_range['earliest'].isoformat() if time_range['earliest'] else None,
            "latest": time_range['latest'].isoformat() if time_range['latest'] else None,
        }
    }

if __name__ == '__main__':
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=5000, reload=True)
