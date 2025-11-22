"""
AI-powered proctoring and cheating detection system
"""
import numpy as np
import pandas as pd
from django.db.models import Avg, Count, Q, F
from django.utils import timezone
from datetime import timedelta
from typing import Dict, List, Tuple, Optional
import json
import logging
import hashlib
import re

import base64

# OpenCV import - handle gracefully if not available
try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError as e:
    logger.warning("OpenCV not available: %s. Face detection will be disabled.", e)
    cv2 = None
    OPENCV_AVAILABLE = False

from .models import (
    Exam, ExamAttempt, ExamProctoring, ExamViolation, 
    QuestionEvaluation
)
from accounts.models import User

logger = logging.getLogger(__name__)


class AIProctoringSystem:
    """Advanced AI-powered proctoring and cheating detection"""
    
    def __init__(self):
        self.cheating_thresholds = {
            'answer_similarity': 0.85,  # 85% similarity threshold
            'time_anomaly': 2.0,        # 2 standard deviations
            'pattern_anomaly': 0.8,     # 80% pattern match
            'behavioral_anomaly': 0.7,  # 70% behavioral deviation
            'device_anomaly': 0.9       # 90% device fingerprint match
        }
        
        self.violation_types = {
            'answer_copying': 'Answer Copying',
            'time_manipulation': 'Time Manipulation',
            'pattern_cheating': 'Pattern-based Cheating',
            'behavioral_anomaly': 'Behavioral Anomaly',
            'device_switching': 'Device Switching',
            'tab_switching': 'Tab Switching',
            'copy_paste': 'Copy-Paste Detection',
            'suspicious_timing': 'Suspicious Timing',
            'answer_similarity': 'Answer Similarity',
            'mouse_anomaly': 'Mouse Movement Anomaly'
        }
        
        # Initialize lightweight face detector (Haar cascade)
        self.face_detector = None
        if OPENCV_AVAILABLE and cv2 is not None:
            try:
                self.face_detector = cv2.CascadeClassifier(
                    cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
                )
                if self.face_detector.empty():
                    logger.warning("Failed to load haarcascade_frontalface_default.xml - face detector disabled")
                    self.face_detector = None
            except Exception as exc:
                logger.error("Failed to initialize face detector: %s", exc)
                self.face_detector = None

    def analyze_snapshot(self, image_data: str) -> Dict:
        """
        Perform lightweight analysis on a webcam snapshot.
        Returns success flag, detected faces, and violation list.
        """
        if not OPENCV_AVAILABLE or cv2 is None:
            logger.warning("OpenCV not available; snapshot stored without analysis")
            return {
                'success': False,
                'error': 'OpenCV not available',
                'message': 'OpenCV library not installed or not available',
                'violations': [],
                'faces_detected': 0
            }
        
        try:
            img_bytes = base64.b64decode(image_data)
            np_arr = np.frombuffer(img_bytes, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

            if frame is None:
                raise ValueError("Unable to decode image")

            height, width = frame.shape[:2]
            grayscale = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            violations = []

            if not self.face_detector:
                logger.warning("Face detector unavailable; skipping detection.")
                return {
                    'success': True,
                    'message': 'Face detector unavailable; snapshot stored',
                    'violations': [],
                    'faces_detected': 0
                }

            faces = self.face_detector.detectMultiScale(grayscale, scaleFactor=1.1, minNeighbors=5)
            face_count = len(faces)

            if face_count == 0:
                violations.append({
                    'type': 'no_face',
                    'severity': 'high',
                    'message': 'No face detected in snapshot',
                    'confidence': 0.9
                })
            elif face_count > 1:
                violations.append({
                    'type': 'multiple_faces',
                    'severity': 'high',
                    'message': f'{face_count} faces detected',
                    'confidence': min(0.5 + 0.1 * face_count, 0.95)
                })
            else:
                # Single face detected – simple heuristic for looking away
                (x, y, w, h) = faces[0]
                face_center_x = x + w / 2
                normalized_x = face_center_x / width
                if normalized_x < 0.25 or normalized_x > 0.75:
                    violations.append({
                        'type': 'looking_away',
                        'severity': 'medium',
                        'message': 'Face near screen edge; possible looking away',
                        'confidence': 0.6
                    })

            return {
                'success': True,
                'faces_detected': face_count,
                'violations': violations
            }

        except Exception as exc:
            logger.error("Snapshot analysis failed: %s", exc)
            return {
                'success': False,
                'error': str(exc),
                'message': 'Snapshot stored but analysis failed'
            }
    
    def analyze_exam_session(self, attempt_id: int) -> Dict:
        """Comprehensive analysis of an exam session for cheating detection"""
        try:
            attempt = ExamAttempt.objects.get(id=attempt_id)
            
            # Get proctoring data
            proctoring_data = self._get_proctoring_data(attempt)
            
            # Run various detection algorithms
            detections = {
                'answer_similarity': self._detect_answer_similarity(attempt),
                'time_anomalies': self._detect_time_anomalies(attempt),
                'behavioral_anomalies': self._detect_behavioral_anomalies(attempt, proctoring_data),
                'device_anomalies': self._detect_device_anomalies(attempt, proctoring_data),
                'pattern_cheating': self._detect_pattern_cheating(attempt),
                'mouse_anomalies': self._detect_mouse_anomalies(proctoring_data),
                'tab_switching': self._detect_tab_switching(proctoring_data),
                'copy_paste_detection': self._detect_copy_paste(proctoring_data)
            }
            
            # Calculate overall risk score
            risk_score = self._calculate_risk_score(detections)
            
            # Generate violations
            violations = self._generate_violations(attempt, detections, risk_score)
            
            # Update proctoring record
            self._update_proctoring_record(attempt, detections, risk_score, violations)
            
            return {
                'attempt_id': attempt_id,
                'student_id': attempt.student.id,
                'exam_id': attempt.exam.id,
                'risk_score': risk_score,
                'risk_level': self._get_risk_level(risk_score),
                'detections': detections,
                'violations': violations,
                'recommendations': self._generate_recommendations(detections, risk_score),
                'confidence': self._calculate_confidence(detections),
                'analyzed_at': timezone.now().isoformat()
            }
            
        except ExamAttempt.DoesNotExist:
            return {'error': 'Exam attempt not found'}
        except Exception as e:
            logger.error(f"Error analyzing exam session: {e}")
            return {'error': str(e)}
    
    def detect_real_time_violations(self, attempt_id: int, event_data: Dict) -> Dict:
        """Real-time violation detection during exam"""
        try:
            attempt = ExamAttempt.objects.get(id=attempt_id)
            
            violations = []
            
            # Check for tab switching
            if event_data.get('event_type') == 'tab_switch':
                if self._is_suspicious_tab_switch(event_data):
                    violations.append({
                        'type': 'tab_switching',
                        'severity': 'medium',
                        'description': 'Suspicious tab switching detected',
                        'timestamp': event_data.get('timestamp'),
                        'confidence': 0.8
                    })
            
            # Check for copy-paste
            if event_data.get('event_type') == 'copy_paste':
                if self._is_suspicious_copy_paste(event_data):
                    violations.append({
                        'type': 'copy_paste',
                        'severity': 'high',
                        'description': 'Copy-paste activity detected',
                        'timestamp': event_data.get('timestamp'),
                        'confidence': 0.9
                    })
            
            # Check for mouse anomalies
            if event_data.get('event_type') == 'mouse_movement':
                if self._is_suspicious_mouse_movement(event_data):
                    violations.append({
                        'type': 'mouse_anomaly',
                        'severity': 'low',
                        'description': 'Unusual mouse movement pattern',
                        'timestamp': event_data.get('timestamp'),
                        'confidence': 0.6
                    })
            
            # Check for time anomalies
            if event_data.get('event_type') == 'question_answer':
                if self._is_suspicious_timing(event_data, attempt):
                    violations.append({
                        'type': 'suspicious_timing',
                        'severity': 'medium',
                        'description': 'Suspicious answer timing detected',
                        'timestamp': event_data.get('timestamp'),
                        'confidence': 0.7
                    })
            
            # Save violations
            for violation in violations:
                self._save_violation(attempt, violation)
            
            return {
                'attempt_id': attempt_id,
                'violations_detected': len(violations),
                'violations': violations,
                'timestamp': timezone.now().isoformat()
            }
            
        except ExamAttempt.DoesNotExist:
            return {'error': 'Exam attempt not found'}
        except Exception as e:
            logger.error(f"Error in real-time detection: {e}")
            return {'error': str(e)}
    
    def get_proctoring_dashboard(self, exam_id: int) -> Dict:
        """Get comprehensive proctoring dashboard for an exam"""
        try:
            exam = Exam.objects.get(id=exam_id)
            
            # Get all attempts for this exam
            attempts = ExamAttempt.objects.filter(exam=exam, status='submitted')
            
            # Get proctoring data
            proctoring_data = ExamProctoring.objects.filter(attempt__exam=exam)
            violations = ExamViolation.objects.filter(attempt__exam=exam)
            
            # Calculate statistics
            stats = self._calculate_proctoring_statistics(attempts, proctoring_data, violations)
            
            # Get high-risk attempts
            high_risk_attempts = self._get_high_risk_attempts(attempts)
            
            # Get violation summary
            violation_summary = self._get_violation_summary(violations)
            
            # Get behavioral patterns
            behavioral_patterns = self._analyze_behavioral_patterns(proctoring_data)
            
            return {
                'exam_id': exam_id,
                'exam_title': exam.title,
                'statistics': stats,
                'high_risk_attempts': high_risk_attempts,
                'violation_summary': violation_summary,
                'behavioral_patterns': behavioral_patterns,
                'recommendations': self._generate_proctoring_recommendations(stats, violations),
                'generated_at': timezone.now().isoformat()
            }
            
        except Exam.DoesNotExist:
            return {'error': 'Exam not found'}
        except Exception as e:
            logger.error(f"Error getting proctoring dashboard: {e}")
            return {'error': str(e)}
    
    def _get_proctoring_data(self, attempt: ExamAttempt) -> Dict:
        """Get proctoring data for an attempt"""
        try:
            proctoring = ExamProctoring.objects.get(attempt=attempt)
            return {
                'mouse_movements': json.loads(proctoring.mouse_movements or '[]'),
                'keyboard_events': json.loads(proctoring.keyboard_events or '[]'),
                'tab_switches': json.loads(proctoring.tab_switches or '[]'),
                'copy_paste_events': json.loads(proctoring.copy_paste_events or '[]'),
                'device_info': json.loads(proctoring.device_info or '{}'),
                'browser_info': json.loads(proctoring.browser_info or '{}'),
                'screen_resolution': proctoring.screen_resolution,
                'timezone': proctoring.timezone,
                'ip_address': proctoring.ip_address,
                'user_agent': proctoring.user_agent
            }
        except ExamProctoring.DoesNotExist:
            return {}
    
    def _detect_answer_similarity(self, attempt: ExamAttempt) -> Dict:
        """Detect answer similarity with other students"""
        try:
            # Get other attempts for the same exam
            other_attempts = ExamAttempt.objects.filter(
                exam=attempt.exam,
                status='submitted'
            ).exclude(id=attempt.id)
            
            if not other_attempts.exists():
                return {'detected': False, 'similarity_score': 0, 'similar_attempts': []}
            
            # Get evaluations for this attempt
            current_evaluations = QuestionEvaluation.objects.filter(attempt=attempt)
            
            similar_attempts = []
            max_similarity = 0
            
            for other_attempt in other_attempts:
                other_evaluations = QuestionEvaluation.objects.filter(attempt=other_attempt)
                
                # Calculate similarity
                similarity = self._calculate_answer_similarity(current_evaluations, other_evaluations)
                
                if similarity > self.cheating_thresholds['answer_similarity']:
                    similar_attempts.append({
                        'attempt_id': other_attempt.id,
                        'student_id': other_attempt.student.id,
                        'similarity_score': similarity
                    })
                    max_similarity = max(max_similarity, similarity)
            
            return {
                'detected': len(similar_attempts) > 0,
                'similarity_score': max_similarity,
                'similar_attempts': similar_attempts,
                'threshold': self.cheating_thresholds['answer_similarity']
            }
            
        except Exception as e:
            logger.error(f"Error detecting answer similarity: {e}")
            return {'detected': False, 'error': str(e)}
    
    def _detect_time_anomalies(self, attempt: ExamAttempt) -> Dict:
        """Detect time-based anomalies"""
        try:
            # Get question evaluations
            evaluations = QuestionEvaluation.objects.filter(attempt=attempt).order_by('question_number')
            
            if not evaluations.exists():
                return {'detected': False, 'anomalies': []}
            
            # Calculate time per question
            time_per_question = []
            for i, eval in enumerate(evaluations):
                if i == 0:
                    time_spent = 0
                else:
                    time_spent = (eval.created_at - evaluations[i-1].created_at).total_seconds()
                time_per_question.append(time_spent)
            
            # Detect anomalies
            anomalies = []
            if len(time_per_question) > 1:
                mean_time = np.mean(time_per_question)
                std_time = np.std(time_per_question)
                
                for i, time in enumerate(time_per_question):
                    if abs(time - mean_time) > self.cheating_thresholds['time_anomaly'] * std_time:
                        anomalies.append({
                            'question_number': i + 1,
                            'time_spent': time,
                            'expected_time': mean_time,
                            'deviation': abs(time - mean_time) / std_time if std_time > 0 else 0
                        })
            
            return {
                'detected': len(anomalies) > 0,
                'anomalies': anomalies,
                'average_time_per_question': np.mean(time_per_question) if time_per_question else 0
            }
            
        except Exception as e:
            logger.error(f"Error detecting time anomalies: {e}")
            return {'detected': False, 'error': str(e)}
    
    def _detect_behavioral_anomalies(self, attempt: ExamAttempt, proctoring_data: Dict) -> Dict:
        """Detect behavioral anomalies"""
        try:
            anomalies = []
            
            # Check for unusual mouse patterns
            if proctoring_data.get('mouse_movements'):
                mouse_anomalies = self._analyze_mouse_patterns(proctoring_data['mouse_movements'])
                if mouse_anomalies['is_anomalous']:
                    anomalies.append({
                        'type': 'mouse_pattern',
                        'description': 'Unusual mouse movement pattern',
                        'confidence': mouse_anomalies['confidence']
                    })
            
            # Check for unusual keyboard patterns
            if proctoring_data.get('keyboard_events'):
                keyboard_anomalies = self._analyze_keyboard_patterns(proctoring_data['keyboard_events'])
                if keyboard_anomalies['is_anomalous']:
                    anomalies.append({
                        'type': 'keyboard_pattern',
                        'description': 'Unusual keyboard input pattern',
                        'confidence': keyboard_anomalies['confidence']
                    })
            
            # Check for unusual timing patterns
            timing_anomalies = self._analyze_timing_patterns(attempt)
            if timing_anomalies['is_anomalous']:
                anomalies.append({
                    'type': 'timing_pattern',
                    'description': 'Unusual timing pattern',
                    'confidence': timing_anomalies['confidence']
                })
            
            return {
                'detected': len(anomalies) > 0,
                'anomalies': anomalies,
                'overall_confidence': np.mean([a['confidence'] for a in anomalies]) if anomalies else 0
            }
            
        except Exception as e:
            logger.error(f"Error detecting behavioral anomalies: {e}")
            return {'detected': False, 'error': str(e)}
    
    def _detect_device_anomalies(self, attempt: ExamAttempt, proctoring_data: Dict) -> Dict:
        """Detect device switching or anomalies"""
        try:
            anomalies = []
            
            # Check for device fingerprint changes
            if proctoring_data.get('device_info'):
                device_hash = self._generate_device_hash(proctoring_data['device_info'])
                
                # Check against previous attempts
                previous_attempts = ExamAttempt.objects.filter(
                    student=attempt.student,
                    status='submitted'
                ).exclude(id=attempt.id).order_by('-submitted_at')[:5]
                
                for prev_attempt in previous_attempts:
                    try:
                        prev_proctoring = ExamProctoring.objects.get(attempt=prev_attempt)
                        prev_device_info = json.loads(prev_proctoring.device_info or '{}')
                        prev_device_hash = self._generate_device_hash(prev_device_info)
                        
                        if device_hash != prev_device_hash:
                            anomalies.append({
                                'type': 'device_switch',
                                'description': 'Device fingerprint changed',
                                'confidence': 0.9,
                                'previous_device': prev_device_hash,
                                'current_device': device_hash
                            })
                            break
                    except ExamProctoring.DoesNotExist:
                        continue
            
            # Check for IP address changes
            if proctoring_data.get('ip_address'):
                ip_anomalies = self._check_ip_anomalies(attempt, proctoring_data['ip_address'])
                if ip_anomalies:
                    anomalies.extend(ip_anomalies)
            
            return {
                'detected': len(anomalies) > 0,
                'anomalies': anomalies
            }
            
        except Exception as e:
            logger.error(f"Error detecting device anomalies: {e}")
            return {'detected': False, 'error': str(e)}
    
    def _detect_pattern_cheating(self, attempt: ExamAttempt) -> Dict:
        """Detect pattern-based cheating (e.g., systematic wrong answers)"""
        try:
            evaluations = QuestionEvaluation.objects.filter(attempt=attempt)
            
            if not evaluations.exists():
                return {'detected': False, 'patterns': []}
            
            patterns = []
            
            # Check for systematic wrong answers
            wrong_answers = [e for e in evaluations if not e.is_correct]
            if len(wrong_answers) > len(evaluations) * 0.8:  # More than 80% wrong
                patterns.append({
                    'type': 'systematic_wrong_answers',
                    'description': 'Systematic pattern of wrong answers',
                    'confidence': 0.7,
                    'wrong_percentage': len(wrong_answers) / len(evaluations) * 100
                })
            
            # Check for answer pattern (A, B, C, D, A, B, C, D...)
            answers = [e.student_answer for e in evaluations.order_by('question_number')]
            if self._is_pattern_sequence(answers):
                patterns.append({
                    'type': 'sequential_pattern',
                    'description': 'Sequential answer pattern detected',
                    'confidence': 0.8,
                    'pattern': answers[:10]  # First 10 answers
                })
            
            # Check for all same answers
            if len(set(answers)) == 1 and len(answers) > 3:
                patterns.append({
                    'type': 'all_same_answers',
                    'description': 'All answers are the same',
                    'confidence': 0.9,
                    'answer': answers[0]
                })
            
            return {
                'detected': len(patterns) > 0,
                'patterns': patterns
            }
            
        except Exception as e:
            logger.error(f"Error detecting pattern cheating: {e}")
            return {'detected': False, 'error': str(e)}
    
    def _detect_mouse_anomalies(self, proctoring_data: Dict) -> Dict:
        """Detect mouse movement anomalies"""
        try:
            mouse_movements = proctoring_data.get('mouse_movements', [])
            
            if not mouse_movements:
                return {'detected': False, 'anomalies': []}
            
            anomalies = []
            
            # Check for too few mouse movements (possible automation)
            if len(mouse_movements) < 10:
                anomalies.append({
                    'type': 'insufficient_mouse_movement',
                    'description': 'Very few mouse movements detected',
                    'confidence': 0.8
                })
            
            # Check for too many mouse movements (possible nervousness or cheating)
            if len(mouse_movements) > 1000:
                anomalies.append({
                    'type': 'excessive_mouse_movement',
                    'description': 'Excessive mouse movements detected',
                    'confidence': 0.6
                })
            
            # Check for circular mouse patterns
            if self._has_circular_pattern(mouse_movements):
                anomalies.append({
                    'type': 'circular_mouse_pattern',
                    'description': 'Circular mouse movement pattern detected',
                    'confidence': 0.7
                })
            
            return {
                'detected': len(anomalies) > 0,
                'anomalies': anomalies
            }
            
        except Exception as e:
            logger.error(f"Error detecting mouse anomalies: {e}")
            return {'detected': False, 'error': str(e)}
    
    def _detect_tab_switching(self, proctoring_data: Dict) -> Dict:
        """Detect suspicious tab switching"""
        try:
            tab_switches = proctoring_data.get('tab_switches', [])
            
            if not tab_switches:
                return {'detected': False, 'switches': []}
            
            suspicious_switches = []
            
            for switch in tab_switches:
                # Check for switches to suspicious domains
                if self._is_suspicious_domain(switch.get('url', '')):
                    suspicious_switches.append({
                        'timestamp': switch.get('timestamp'),
                        'url': switch.get('url'),
                        'reason': 'Suspicious domain',
                        'confidence': 0.9
                    })
                
                # Check for frequent switching
                if switch.get('frequency', 0) > 10:  # More than 10 switches per minute
                    suspicious_switches.append({
                        'timestamp': switch.get('timestamp'),
                        'url': switch.get('url'),
                        'reason': 'Frequent tab switching',
                        'confidence': 0.7
                    })
            
            return {
                'detected': len(suspicious_switches) > 0,
                'switches': suspicious_switches,
                'total_switches': len(tab_switches)
            }
            
        except Exception as e:
            logger.error(f"Error detecting tab switching: {e}")
            return {'detected': False, 'error': str(e)}
    
    def _detect_copy_paste(self, proctoring_data: Dict) -> Dict:
        """Detect copy-paste activities"""
        try:
            copy_paste_events = proctoring_data.get('copy_paste_events', [])
            
            if not copy_paste_events:
                return {'detected': False, 'events': []}
            
            suspicious_events = []
            
            for event in copy_paste_events:
                # Check for copy-paste from external sources
                if event.get('source') == 'external':
                    suspicious_events.append({
                        'timestamp': event.get('timestamp'),
                        'content': event.get('content', '')[:100],  # First 100 chars
                        'reason': 'Copy from external source',
                        'confidence': 0.9
                    })
                
                # Check for large text copy-paste
                if len(event.get('content', '')) > 500:
                    suspicious_events.append({
                        'timestamp': event.get('timestamp'),
                        'content': event.get('content', '')[:100],
                        'reason': 'Large text copy-paste',
                        'confidence': 0.8
                    })
            
            return {
                'detected': len(suspicious_events) > 0,
                'events': suspicious_events,
                'total_events': len(copy_paste_events)
            }
            
        except Exception as e:
            logger.error(f"Error detecting copy-paste: {e}")
            return {'detected': False, 'error': str(e)}
    
    def _calculate_answer_similarity(self, evaluations1, evaluations2) -> float:
        """Calculate similarity between two sets of answers"""
        try:
            if not evaluations1.exists() or not evaluations2.exists():
                return 0.0
            
            # Create answer dictionaries
            answers1 = {e.question_number: e.student_answer for e in evaluations1}
            answers2 = {e.question_number: e.student_answer for e in evaluations2}
            
            # Find common questions
            common_questions = set(answers1.keys()) & set(answers2.keys())
            
            if not common_questions:
                return 0.0
            
            # Calculate similarity
            matches = 0
            for q_num in common_questions:
                if answers1[q_num] == answers2[q_num]:
                    matches += 1
            
            return matches / len(common_questions)
            
        except Exception as e:
            logger.error(f"Error calculating answer similarity: {e}")
            return 0.0
    
    def _generate_device_hash(self, device_info: Dict) -> str:
        """Generate a hash for device fingerprinting"""
        try:
            # Create a string from device info
            device_string = f"{device_info.get('screen_resolution', '')}-{device_info.get('timezone', '')}-{device_info.get('user_agent', '')}"
            return hashlib.md5(device_string.encode()).hexdigest()
        except Exception:
            return "unknown"
    
    def _is_suspicious_tab_switch(self, event_data: Dict) -> bool:
        """Check if tab switch is suspicious"""
        url = event_data.get('url', '').lower()
        suspicious_domains = ['google.com', 'wikipedia.org', 'stackoverflow.com', 'chegg.com', 'coursehero.com']
        
        return any(domain in url for domain in suspicious_domains)
    
    def _is_suspicious_copy_paste(self, event_data: Dict) -> bool:
        """Check if copy-paste is suspicious"""
        content = event_data.get('content', '')
        source = event_data.get('source', '')
        
        # Check for external source
        if source == 'external':
            return True
        
        # Check for large content
        if len(content) > 500:
            return True
        
        return False
    
    def _is_suspicious_mouse_movement(self, event_data: Dict) -> bool:
        """Check if mouse movement is suspicious"""
        # This would implement more sophisticated mouse movement analysis
        return False
    
    def _is_suspicious_timing(self, event_data: Dict, attempt: ExamAttempt) -> bool:
        """Check if timing is suspicious"""
        # This would implement timing analysis
        return False
    
    def _analyze_mouse_patterns(self, mouse_movements: List) -> Dict:
        """Analyze mouse movement patterns"""
        # Simplified analysis
        return {
            'is_anomalous': len(mouse_movements) < 5 or len(mouse_movements) > 1000,
            'confidence': 0.7
        }
    
    def _analyze_keyboard_patterns(self, keyboard_events: List) -> Dict:
        """Analyze keyboard input patterns"""
        # Simplified analysis
        return {
            'is_anomalous': len(keyboard_events) < 10,
            'confidence': 0.6
        }
    
    def _analyze_timing_patterns(self, attempt: ExamAttempt) -> Dict:
        """Analyze timing patterns"""
        # Simplified analysis
        return {
            'is_anomalous': False,
            'confidence': 0.5
        }
    
    def _check_ip_anomalies(self, attempt: ExamAttempt, current_ip: str) -> List[Dict]:
        """Check for IP address anomalies"""
        # This would implement IP analysis
        return []
    
    def _is_pattern_sequence(self, answers: List[str]) -> bool:
        """Check if answers follow a sequential pattern"""
        if len(answers) < 4:
            return False
        
        # Check for A, B, C, D pattern
        pattern = ['A', 'B', 'C', 'D']
        for i, answer in enumerate(answers[:4]):
            if answer != pattern[i % 4]:
                return False
        
        return True
    
    def _has_circular_pattern(self, mouse_movements: List) -> bool:
        """Check for circular mouse movement patterns"""
        # Simplified circular pattern detection
        return False
    
    def _is_suspicious_domain(self, url: str) -> bool:
        """Check if domain is suspicious"""
        suspicious_domains = ['google.com', 'wikipedia.org', 'stackoverflow.com', 'chegg.com']
        return any(domain in url.lower() for domain in suspicious_domains)
    
    def _calculate_risk_score(self, detections: Dict) -> float:
        """Calculate overall risk score"""
        weights = {
            'answer_similarity': 0.3,
            'time_anomalies': 0.2,
            'behavioral_anomalies': 0.2,
            'device_anomalies': 0.15,
            'pattern_cheating': 0.1,
            'mouse_anomalies': 0.05
        }
        
        risk_score = 0
        for detection_type, weight in weights.items():
            if detections.get(detection_type, {}).get('detected', False):
                risk_score += weight
        
        return min(1.0, risk_score)
    
    def _get_risk_level(self, risk_score: float) -> str:
        """Get risk level based on score"""
        if risk_score >= 0.8:
            return 'high'
        elif risk_score >= 0.5:
            return 'medium'
        else:
            return 'low'
    
    def _generate_violations(self, attempt: ExamAttempt, detections: Dict, risk_score: float) -> List[Dict]:
        """Generate violations based on detections"""
        violations = []
        
        for detection_type, detection in detections.items():
            if detection.get('detected', False):
                violation = {
                    'attempt': attempt,
                    'violation_type': detection_type,
                    'description': f"{self.violation_types.get(detection_type, detection_type)} detected",
                    'severity': self._get_risk_level(risk_score),
                    'confidence': detection.get('confidence', 0.5),
                    'details': json.dumps(detection),
                    'detected_at': timezone.now()
                }
                violations.append(violation)
        
        return violations
    
    def _update_proctoring_record(self, attempt: ExamAttempt, detections: Dict, risk_score: float, violations: List[Dict]):
        """Update proctoring record with analysis results"""
        try:
            proctoring, created = ExamProctoring.objects.get_or_create(attempt=attempt)
            proctoring.risk_score = risk_score
            proctoring.analysis_results = json.dumps(detections)
            proctoring.analyzed_at = timezone.now()
            proctoring.save()
            
            # Save violations
            for violation in violations:
                ExamViolation.objects.create(**violation)
                
        except Exception as e:
            logger.error(f"Error updating proctoring record: {e}")
    
    def _save_violation(self, attempt: ExamAttempt, violation: Dict):
        """Save a violation"""
        try:
            ExamViolation.objects.create(
                attempt=attempt,
                violation_type=violation['type'],
                description=violation['description'],
                severity=violation['severity'],
                confidence=violation['confidence'],
                details=json.dumps(violation),
                detected_at=timezone.now()
            )
        except Exception as e:
            logger.error(f"Error saving violation: {e}")
    
    def _calculate_confidence(self, detections: Dict) -> float:
        """Calculate overall confidence in the analysis"""
        confidences = []
        for detection in detections.values():
            if isinstance(detection, dict) and 'confidence' in detection:
                confidences.append(detection['confidence'])
        
        return np.mean(confidences) if confidences else 0.5
    
    def _generate_recommendations(self, detections: Dict, risk_score: float) -> List[str]:
        """Generate recommendations based on analysis"""
        recommendations = []
        
        if risk_score > 0.8:
            recommendations.append("High risk detected - manual review recommended")
        
        if detections.get('answer_similarity', {}).get('detected', False):
            recommendations.append("Answer similarity detected - investigate potential collaboration")
        
        if detections.get('tab_switching', {}).get('detected', False):
            recommendations.append("Suspicious tab switching detected - review browser activity")
        
        if detections.get('copy_paste', {}).get('detected', False):
            recommendations.append("Copy-paste activity detected - review answer sources")
        
        return recommendations
    
    def _calculate_proctoring_statistics(self, attempts, proctoring_data, violations) -> Dict:
        """Calculate proctoring statistics"""
        total_attempts = attempts.count()
        high_risk_attempts = proctoring_data.filter(risk_score__gte=0.8).count()
        total_violations = violations.count()
        
        return {
            'total_attempts': total_attempts,
            'high_risk_attempts': high_risk_attempts,
            'risk_percentage': (high_risk_attempts / total_attempts * 100) if total_attempts > 0 else 0,
            'total_violations': total_violations,
            'average_risk_score': proctoring_data.aggregate(avg_risk=Avg('risk_score'))['avg_risk'] or 0
        }
    
    def _get_high_risk_attempts(self, attempts) -> List[Dict]:
        """Get high-risk attempts"""
        high_risk = []
        for attempt in attempts:
            try:
                proctoring = ExamProctoring.objects.get(attempt=attempt)
                if proctoring.risk_score >= 0.8:
                    high_risk.append({
                        'attempt_id': attempt.id,
                        'student_id': attempt.student.id,
                        'student_name': attempt.student.get_full_name() or attempt.student.email,
                        'risk_score': proctoring.risk_score,
                        'analyzed_at': proctoring.analyzed_at
                    })
            except ExamProctoring.DoesNotExist:
                continue
        
        return high_risk
    
    def _get_violation_summary(self, violations) -> Dict:
        """Get violation summary"""
        violation_counts = {}
        for violation in violations:
            violation_type = violation.violation_type
            violation_counts[violation_type] = violation_counts.get(violation_type, 0) + 1
        
        return violation_counts
    
    def _analyze_behavioral_patterns(self, proctoring_data) -> Dict:
        """Analyze behavioral patterns"""
        # This would implement more sophisticated behavioral analysis
        return {
            'common_patterns': [],
            'anomalies': [],
            'recommendations': []
        }
    
    def _generate_proctoring_recommendations(self, stats: Dict, violations) -> List[str]:
        """Generate proctoring recommendations"""
        recommendations = []
        
        if stats['risk_percentage'] > 20:
            recommendations.append("High risk percentage detected - consider additional proctoring measures")
        
        if stats['total_violations'] > stats['total_attempts'] * 0.5:
            recommendations.append("High violation rate - review proctoring settings")
        
        return recommendations