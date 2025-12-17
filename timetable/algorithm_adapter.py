"""
Adapter functions to convert optimization.py payload format to genetic_algorithm.py format
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Tuple
from .optimization import TeacherDTO


@dataclass
class BatchDTO:
    """Data structure for batch in algorithm format"""
    batch_code: str
    sub_teachers: Dict[str, Dict[str, Any]]  # key: subject, value: teacher/subject config


def convert_teachers_to_algorithm_format(
    teachers_list: List[Dict[str, Any]]
) -> Dict[str, TeacherDTO]:
    """
    Convert teachers from list format to dict format with TeacherDTO objects.
    
    Input: [{"Code": "TCH-001", "avilable_slots": ["m1", "m2"], ...}, ...]
    Output: {"TCH-001": TeacherDTO(...), ...}
    """
    teachers_dict = {}
    for idx, teacher_data in enumerate(teachers_list, start=1):
        code = teacher_data.get("Code", f"t{idx}")
        dto = TeacherDTO(
            name=teacher_data.get("Name", ""),
            code=code,
            employ_id=str(teacher_data.get("Employ-id", "")),
            subject=teacher_data.get("subjects", ""),
            available_slots=teacher_data.get("avilable_slots", [])
        )
        teachers_dict[code] = dto
    
    return teachers_dict


def convert_batches_to_algorithm_format(
    batches_dict: Dict[str, Dict[str, Any]],
    teachers_dict: Dict[str, TeacherDTO]
) -> Dict[str, Any]:
    """
    Convert batches from optimization format to algorithm format.
    
    Input: {
        "BATCH-001": {
            "sub_teachers": [
                {"teacher": "TCH-001", "min_class": 8, "max_class": 10, ...}
            ]
        }
    }
    
    Output: {
        "BATCH-001": {
            "batch_code": "BATCH-001",
            "sub_teachers": {
                "subject_key": {
                    "teacher": TeacherDTO(...),
                    "subject": "Physics",
                    "min_class_per_week": 8,
                    "max_class_per_week": 10,
                    "min_class_per_day": 1,
                    "max_class_per_day": 2
                }
            }
        }
    }
    """
    algorithm_batches = {}
    
    for batch_code, batch_data in batches_dict.items():
        sub_teachers_dict = {}
        sub_teachers_list = batch_data.get("sub_teachers", [])
        
        for idx, sub_data in enumerate(sub_teachers_list):
            teacher_code = sub_data.get("teacher", "")
            teacher_obj = teachers_dict.get(teacher_code)
            
            if not teacher_obj:
                continue  # Skip if teacher not found
            
            # Extract subject from sub_data (now includes subject from optimization.py)
            subject = sub_data.get("subject", "")
            if not subject:
                # Fallback: extract from teacher's subjects
                teacher_subjects_str = teacher_obj.subject or ""
                teacher_subjects = [s.strip() for s in teacher_subjects_str.split(",") if s.strip()] if teacher_subjects_str else []
                subject = teacher_subjects[0] if teacher_subjects else f"Subject_{idx}"
            subject_key = f"{subject}_{idx}"  # Unique key for each subject-teacher combo
            
            sub_teachers_dict[subject_key] = {
                "teacher": teacher_obj,
                "subject": subject,
                "min_class_per_week": int(sub_data.get("min_class", 0)),
                "max_class_per_week": int(sub_data.get("max_class", 0)),
                "min_class_per_day": int(sub_data.get("min_class_day", 0)),
                "max_class_per_day": int(sub_data.get("max_class_day", 0))
            }
        
        algorithm_batches[batch_code] = type('Batch', (), {
            'batch_code': batch_code,
            'sub_teachers': sub_teachers_dict
        })()
    
    return algorithm_batches

