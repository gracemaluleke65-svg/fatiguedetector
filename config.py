import os
from dataclasses import dataclass
from typing import List

@dataclass
class Config:
    # App version
    APP_VERSION: str = "2.0.0"
    
    # Detection thresholds (seconds)
    ALERT_THRESHOLD_SECONDS: float = 1.0      # Start alarm
    VOICE_THRESHOLD_SECONDS: float = 2.0      # Start voice
    BLINK_MAX_SECONDS: float = 0.5            # Normal blink threshold
    NO_FACE_ALARM_DELAY: float = 1.0          # No-face alarm delay
    
    # Adaptive threshold parameters
    MIN_EAR_THRESHOLD: float = 0.15
    HYSTERESIS_MARGIN: float = 0.02
    EMA_ALPHA: float = 0.1                    # Exponential moving average
    
    # Head pose thresholds (degrees)
    YAW_THRESHOLD: float = 35.0
    PITCH_THRESHOLD: float = 30.0
    
    # Processing
    PROCESSING_RESOLUTION: tuple = (320, 240)
    FRAME_SKIP: int = 1                       # Process every Nth frame
    MAX_FRAME_SIZE: int = 2 * 1024 * 1024     # 2MB max frame
    ALERT_DEBOUNCE: float = 2.0               # Seconds between alert logs
    
    # Security
    ALLOWED_ORIGINS: List[str] = None
    
    # Database
    DB_NAME: str = "fatigue.db"
    TRIPS_TABLE: str = "fatigue_trips"
    ALERTS_TABLE: str = "fatigue_alerts"
    
    # Model paths
    SHAPE_PREDICTOR_PATH: str = "shape_predictor_68_face_landmarks.dat"

# Load from environment
config = Config()
config.ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', '*').split(',')
config.DB_NAME = os.environ.get('DB_NAME', config.DB_NAME)
config.SHAPE_PREDICTOR_PATH = os.environ.get('SHAPE_PREDICTOR_PATH', config.SHAPE_PREDICTOR_PATH)
config.ALERT_THRESHOLD_SECONDS = float(os.environ.get('ALERT_THRESHOLD', config.ALERT_THRESHOLD_SECONDS))
config.VOICE_THRESHOLD_SECONDS = float(os.environ.get('VOICE_THRESHOLD', config.VOICE_THRESHOLD_SECONDS))

# Export individual variables for backward compatibility
ALERT_THRESHOLD_SECONDS = config.ALERT_THRESHOLD_SECONDS
VOICE_THRESHOLD_SECONDS = config.VOICE_THRESHOLD_SECONDS
BLINK_MAX_SECONDS = config.BLINK_MAX_SECONDS
NO_FACE_ALARM_DELAY = config.NO_FACE_ALARM_DELAY
DB_NAME = config.DB_NAME
TRIPS_TABLE = config.TRIPS_TABLE
ALERTS_TABLE = config.ALERTS_TABLE
SHAPE_PREDICTOR_PATH = config.SHAPE_PREDICTOR_PATH
ALLOWED_ORIGINS = config.ALLOWED_ORIGINS
APP_VERSION = config.APP_VERSION
PROCESSING_RESOLUTION = config.PROCESSING_RESOLUTION
FRAME_SKIP = config.FRAME_SKIP
MAX_FRAME_SIZE = config.MAX_FRAME_SIZE
ALERT_DEBOUNCE = config.ALERT_DEBOUNCE
MIN_EAR_THRESHOLD = config.MIN_EAR_THRESHOLD
HYSTERESIS_MARGIN = config.HYSTERESIS_MARGIN
EMA_ALPHA = config.EMA_ALPHA
YAW_THRESHOLD = config.YAW_THRESHOLD
PITCH_THRESHOLD = config.PITCH_THRESHOLD