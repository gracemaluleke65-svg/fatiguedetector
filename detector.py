import cv2
import dlib
import numpy as np
import logging
from typing import Dict, Optional, Tuple
import config

logger = logging.getLogger(__name__)

class FaceDetector:
    def __init__(self):
        self._detector = None
        self._predictor = None
        self._face_cascade = None
        self._initialized = False
    
    def initialize(self):
        if self._initialized:
            return
        
        try:
            self._detector = dlib.get_frontal_face_detector()
            self._predictor = dlib.shape_predictor(config.SHAPE_PREDICTOR_PATH)
            
            # Fallback Haar cascade for faster detection on weak hardware
            self._face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            )
            
            self._initialized = True
            logger.info("Face detector initialized")
        except Exception as e:
            logger.error(f"Detector initialization failed: {e}")
            raise
    
    @property
    def detector(self):
        if not self._initialized:
            self.initialize()
        return self._detector
    
    @property
    def predictor(self):
        if not self._initialized:
            self.initialize()
        return self._predictor

# Global detector instance
_face_detector = FaceDetector()

# Landmark indices
LEFT_EYE_INDICES = list(range(36, 42))
RIGHT_EYE_INDICES = list(range(42, 48))
NOSE_TIP = 30
CHIN = 8

def eye_aspect_ratio(eye: np.ndarray) -> float:
    """Calculate EAR with numerical stability"""
    A = np.linalg.norm(eye[1] - eye[5])
    B = np.linalg.norm(eye[2] - eye[4])
    C = np.linalg.norm(eye[0] - eye[3])
    
    if C < 1e-6:
        return 0.5  # Default open value
    
    return (A + B) / (2.0 * C)

def estimate_head_pose(landmarks, face_rect, frame_shape) -> Optional[Dict[str, float]]:
    """Estimate head pose using 3D-2D correspondence"""
    try:
        # 3D model points (approximate)
        model_points = np.array([
            (0.0, 0.0, 0.0),             # Nose tip
            (0.0, -330.0, -65.0),        # Chin
            (-225.0, 170.0, -135.0),     # Left eye left corner
            (225.0, 170.0, -135.0),      # Right eye right corner
            (-150.0, -150.0, -125.0),    # Left mouth corner
            (150.0, -150.0, -125.0)      # Right mouth corner
        ])
        
        # 2D image points
        image_points = np.array([
            (landmarks.part(30).x, landmarks.part(30).y),  # Nose tip
            (landmarks.part(8).x, landmarks.part(8).y),    # Chin
            (landmarks.part(36).x, landmarks.part(36).y),  # Left eye left corner
            (landmarks.part(45).x, landmarks.part(45).y),  # Right eye right corner
            (landmarks.part(48).x, landmarks.part(48).y),  # Left mouth corner
            (landmarks.part(54).x, landmarks.part(54).y)   # Right mouth corner
        ], dtype="double")
        
        # Camera internals
        focal_length = frame_shape[1]
        center = (frame_shape[1] / 2, frame_shape[0] / 2)
        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1]
        ], dtype="double")
        
        dist_coeffs = np.zeros((4, 1))
        
        success, rotation_vector, translation_vector = cv2.solvePnP(
            model_points, image_points, camera_matrix, dist_coeffs
        )
        
        if not success:
            return None
        
        # Convert to Euler angles
        rotation_matrix, _ = cv2.Rodrigues(rotation_vector)
        pose_matrix = cv2.hconcat((rotation_matrix, translation_vector))
        _, _, _, _, _, _, euler_angles = cv2.decomposeProjectionMatrix(
            np.vstack((pose_matrix, [0, 0, 0, 1]))
        )
        
        return {
            'yaw': float(euler_angles[1]),
            'pitch': float(euler_angles[0]),
            'roll': float(euler_angles[2])
        }
        
    except Exception as e:
        logger.debug(f"Pose estimation failed: {e}")
        return None

def get_eye_ear_with_pose(frame: np.ndarray) -> Dict:
    """
    Main detection function with pose estimation
    Returns: {
        'ear_left': float,
        'ear_right': float,
        'face_detected': bool,
        'head_pose': Optional[Dict]
    }
    """
    result = {
        'ear_left': 0.5,
        'ear_right': 0.5,
        'face_detected': False,
        'head_pose': None
    }
    
    if frame is None or frame.size == 0:
        return result
    
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Detect faces
        faces = _face_detector.detector(gray, 0)
        
        if len(faces) == 0:
            return result
        
        # Select largest face
        face = max(faces, key=lambda f: f.area())
        
        # Size filter (face must be > 3% of frame)
        min_area = frame.shape[0] * frame.shape[1] * 0.03
        if face.area() < min_area:
            return result
        
        # Get landmarks
        landmarks = _face_detector.predictor(gray, face)
        
        # Extract eyes
        left_eye = np.array([
            (landmarks.part(i).x, landmarks.part(i).y) 
            for i in LEFT_EYE_INDICES
        ])
        right_eye = np.array([
            (landmarks.part(i).x, landmarks.part(i).y) 
            for i in RIGHT_EYE_INDICES
        ])
        
        # Calculate EAR
        result['ear_left'] = eye_aspect_ratio(left_eye)
        result['ear_right'] = eye_aspect_ratio(right_eye)
        result['face_detected'] = True
        
        # Estimate head pose
        result['head_pose'] = estimate_head_pose(landmarks, face, frame.shape)
        
        return result
        
    except Exception as e:
        logger.error(f"Detection error: {e}")
        return result

def get_eye_ear_fast(frame: np.ndarray) -> Tuple[float, bool]:
    """Legacy wrapper for simple EAR + detection"""
    result = get_eye_ear_with_pose(frame)
    ear = (result['ear_left'] + result['ear_right']) / 2
    return ear, result['face_detected']

# Initialize on module load
try:
    _face_detector.initialize()
except Exception as e:
    logger.warning(f"Deferred detector initialization: {e}")