import os
import base64
import cv2
import numpy as np
import time
import logging
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit, disconnect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import detector
import database
import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # Render captures stdout
)
logger = logging.getLogger(__name__)

# Flask app initialization
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(32))
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Rate limiting (use memory on Render free tier)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory://",  # Use Redis in production if available
    default_limits=["200 per day", "50 per hour"]
)

# SocketIO - CRITICAL: Use threading for Render compatibility
socketio = SocketIO(
    app,
    cors_allowed_origins=os.environ.get('ALLOWED_ORIGINS', '*').split(','),
    async_mode='threading',  # Changed from eventlet for Render stability
    max_http_buffer_size=1e8,
    ping_timeout=10,
    ping_interval=5,
    logger=False,
    engineio_logger=False
)

# Initialize database
database.init_db()

# Trip state management
class TripState:
    def __init__(self):
        self._lock = __import__('threading').Lock()
        self.reset()
    
    def reset(self):
        self.trip_id = None
        self.alert_active = False
        self.eyes_closed_start = None
        self.last_alarm_time = 0
        self.no_face_start = None
        self.no_face_alert_active = False
        self.open_ear_avg = 0.3
        self.adaptive_threshold = 0.2
        self.frame_count = 0
        self.start_time = None
        self.session_id = None
    
    def acquire(self):
        self._lock.acquire()
    
    def release(self):
        self._lock.release()

# Session storage
active_sessions = {}
SESSION_TIMEOUT = 3600

def get_session_state(sid):
    if sid not in active_sessions:
        active_sessions[sid] = TripState()
    return active_sessions[sid]

def cleanup_session(sid):
    if sid in active_sessions:
        state = active_sessions[sid]
        if state.trip_id:
            try:
                database.end_trip(state.trip_id, None, None)
                logger.info(f"Auto-ended trip {state.trip_id}")
            except Exception as e:
                logger.error(f"Failed to auto-end trip: {e}")
        del active_sessions[sid]

@app.route('/')
@limiter.limit("10 per minute")
def index():
    return render_template('index.html', version=config.APP_VERSION)

@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'active_sessions': len(active_sessions)
    })

@app.route('/stats/<int:trip_id>')
def trip_stats(trip_id):
    try:
        stats = database.get_trip_stats(trip_id)
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return jsonify({'error': 'Failed to retrieve stats'}), 500

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    logger.info(f"Client connected: {sid}")
    emit('connected', {
        'status': 'ready',
        'version': config.APP_VERSION,
        'thresholds': {
            'alarm': config.ALERT_THRESHOLD_SECONDS,
            'voice': config.VOICE_THRESHOLD_SECONDS
        }
    })

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    logger.info(f"Client disconnected: {sid}")
    cleanup_session(sid)

@socketio.on('start_trip')
def handle_start_trip():
    sid = request.sid
    state = get_session_state(sid)
    
    try:
        state.acquire()
        
        if state.trip_id:
            database.end_trip(state.trip_id, None, None)
        
        state.reset()
        state.trip_id = database.create_trip()
        state.start_time = time.time()
        state.session_id = sid
        
        logger.info(f"Trip started: {state.trip_id}")
        emit('trip_started', {
            'trip_id': state.trip_id,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Start trip error: {e}")
        emit('error', {'message': 'Failed to start trip'})
    finally:
        state.release()

@socketio.on('end_trip')
def handle_end_trip(data):
    sid = request.sid
    state = get_session_state(sid)
    
    try:
        state.acquire()
        
        if state.trip_id:
            duration_min = int((time.time() - state.start_time) / 60) if state.start_time else None
            database.end_trip(state.trip_id, None, duration_min)
            logger.info(f"Trip ended: {state.trip_id}")
            
            stats = database.get_trip_stats(state.trip_id)
            emit('trip_ended', {
                'status': 'completed',
                'trip_id': state.trip_id,
                'duration_minutes': duration_min,
                'stats': stats
            })
            state.reset()
        else:
            emit('error', {'message': 'No active trip'})
            
    except Exception as e:
        logger.error(f"End trip error: {e}")
        emit('error', {'message': 'Failed to end trip'})
    finally:
        state.release()

@socketio.on('frame')
def handle_frame(data):
    sid = request.sid
    state = get_session_state(sid)
    
    if not state.trip_id:
        emit('error', {'message': 'No active trip'})
        return
    
    state.frame_count += 1
    if state.frame_count % config.FRAME_SKIP != 0:
        return
    
    try:
        if not isinstance(data, str) or ',' not in data:
            emit('error', {'message': 'Invalid frame data'})
            return
            
        image_data = base64.b64decode(data.split(',')[1])
        if len(image_data) > config.MAX_FRAME_SIZE:
            emit('error', {'message': 'Frame too large'})
            return
            
        np_arr = np.frombuffer(image_data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        if frame is None:
            emit('error', {'message': 'Failed to decode frame'})
            return
        
        frame = cv2.resize(frame, config.PROCESSING_RESOLUTION)
        result = detector.get_eye_ear_with_pose(frame)
        current_time = time.time()
        
        response = process_detection(result, state, current_time)
        emit('eye_state', response)
        
    except Exception as e:
        logger.error(f"Frame processing error: {e}")
        emit('eye_state', {'error': 'Processing failed', 'face_detected': False})

def process_detection(result, state, current_time):
    """Core detection logic"""
    ear_left = result['ear_left']
    ear_right = result['ear_right']
    ear = (ear_left + ear_right) / 2
    face_detected = result['face_detected']
    head_pose = result.get('head_pose')
    
    response = {
        'face_detected': face_detected,
        'ear': round(ear, 3),
        'eyes_closed': False,
        'alarm': False,
        'blink': False,
        'closed_duration': 0,
        'no_face_duration': 0,
        'adaptive_threshold': round(state.adaptive_threshold, 3)
    }
    
    if not face_detected:
        return handle_no_face(state, current_time, response)
    
    if state.no_face_start is not None:
        state.no_face_start = None
        state.no_face_alert_active = False
        if not state.alert_active:
            state.alert_active = False
    
    looking_away = False
    if head_pose:
        looking_away = (abs(head_pose['yaw']) > config.YAW_THRESHOLD or 
                       abs(head_pose['pitch']) > config.PITCH_THRESHOLD)
        response['head_pose'] = {
            'yaw': round(head_pose['yaw'], 1),
            'pitch': round(head_pose['pitch'], 1)
        }
    
    if not looking_away and ear > (state.adaptive_threshold + config.HYSTERESIS_MARGIN):
        state.open_ear_avg = (config.EMA_ALPHA * ear + 
                             (1 - config.EMA_ALPHA) * state.open_ear_avg)
        state.adaptive_threshold = max(config.MIN_EAR_THRESHOLD, 
                                      state.open_ear_avg * 0.6)
    
    ear_closed_thresh = state.adaptive_threshold - config.HYSTERESIS_MARGIN
    ear_open_thresh = state.adaptive_threshold + config.HYSTERESIS_MARGIN
    
    if state.eyes_closed_start is not None:
        eyes_closed = not (ear > ear_open_thresh)
    else:
        eyes_closed = (ear < ear_closed_thresh)
    
    if looking_away:
        eyes_closed = False
        state.eyes_closed_start = None
    
    if eyes_closed:
        return handle_eyes_closed(state, current_time, ear, response)
    else:
        return handle_eyes_open(state, current_time, response)

def handle_no_face(state, current_time, response):
    if state.no_face_start is None:
        state.no_face_start = current_time
        state.eyes_closed_start = None
    
    duration = current_time - state.no_face_start
    response['no_face_duration'] = round(duration, 2)
    
    if duration >= config.NO_FACE_ALARM_DELAY:
        if not state.no_face_alert_active:
            state.no_face_alert_active = True
            state.alert_active = True
            state.last_alarm_time = current_time
            database.log_alert(state.trip_id, duration, 'no_face')
            logger.warning(f"NO FACE ALARM: {duration:.2f}s")
        
        response['alarm'] = True
        response['status'] = 'no_face_alarm'
    else:
        response['status'] = 'no_face'
        response['alarm'] = state.alert_active
    
    return response

def handle_eyes_closed(state, current_time, ear, response):
    response['eyes_closed'] = True
    
    if state.eyes_closed_start is None:
        state.eyes_closed_start = current_time
    
    duration = current_time - state.eyes_closed_start
    response['closed_duration'] = round(duration, 2)
    
    if duration < 0.15:
        response['blink'] = True
        response['status'] = 'micro_blink'
    elif duration < config.BLINK_MAX_SECONDS:
        response['blink'] = True
        response['status'] = 'normal_blink'
        if state.alert_active and not state.no_face_alert_active:
            state.alert_active = False
    else:
        response['status'] = 'fatigue_suspected'
        
        if duration >= config.ALERT_THRESHOLD_SECONDS:
            response['alarm'] = True
            
            if (not state.alert_active or 
                current_time - state.last_alarm_time > config.ALERT_DEBOUNCE):
                state.alert_active = True
                state.last_alarm_time = current_time
                database.log_alert(state.trip_id, duration, 'eyes_closed')
                logger.warning(f"FATIGUE ALARM: {duration:.2f}s")
    
    return response

def handle_eyes_open(state, current_time, response):
    if state.eyes_closed_start is not None:
        closed_duration = current_time - state.eyes_closed_start
        if closed_duration < config.BLINK_MAX_SECONDS:
            response['blink'] = True
            response['status'] = 'blink_complete'
    
    state.eyes_closed_start = None
    
    if state.alert_active and not state.no_face_alert_active:
        state.alert_active = False
    
    response['status'] = 'awake'
    response['alarm'] = state.alert_active
    return response

# Production entry point
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)