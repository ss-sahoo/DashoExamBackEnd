"""
Helpers to convert Django models into the plain Python data structures
your optimisation code expects.

We do NOT run the optimisation here – we just prepare data in a clean,
modular, JSON-serialisable format.

Shapes we build (very close to your examples):

- available_slots = {
    'mon': {'m1': '8-9.30', 'm2': '9.40-11.10', ...},
    'tue': {...},
    ...
  }

- teachers = [
    {
      'Employ-id': 34701,
      'Name': 'AK-CAP',
      'Code': 'AK-CAP',
      'subjects': 'a',
      'avilable_slots': ['m1', 'm2', 'tu3', ...],
    },
    ...
  ]

- batches = {
    'HDTN-1A-ZA1': {
        'sub_teachers': [
            {
                'teacher': 'PVS',
                'min_class': 8,
                'max_class': 9,
                'min_class_day': 1,
                'max_class_day': 2,
            },
            ...
        ]
    },
    ...
  }

- fixed_slots = {
    'mon': {
        'm1': {
            'HDTN-1A-ZA1': ('z', 'ZRS'),
            'HDTN-1A-EA1': None,
            ...
        },
        ...
    },
    ...
  }
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Any

from .models import (
    Timetable,
    DaySlot,
    TeacherSlotAvailability,
    BatchFacultyLoad,
    FixedSlot,
)
from accounts.models import User, Batch


DAY_MAP_SHORT = {
    DaySlot.MONDAY: "mon",
    DaySlot.TUESDAY: "tue",
    DaySlot.WEDNESDAY: "wed",
    DaySlot.THURSDAY: "thu",
    DaySlot.FRIDAY: "fri",
    DaySlot.SATURDAY: "sat",
    DaySlot.SUNDAY: "sun",
}


def build_available_slots(timetable: Timetable) -> Dict[str, Dict[str, str]]:
    """
    Build `available_slots` dict from DaySlot rows of a timetable.

    - Keys: 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'
    - Inner keys: slot codes like 'm1', 'tu3' (taken from DaySlot.slot_code)
    - Values: "HH:MM-HH:MM" strings
    """

    slots_by_day: Dict[str, Dict[str, str]] = {}
    qs = timetable.day_slots.all().order_by("day", "slot_number")

    for day_slot in qs:
        day_key = DAY_MAP_SHORT[day_slot.day]
        slots_by_day.setdefault(day_key, {})

        # If slot_code is empty, fall back to pattern like 'm1', 'tu2', etc.
        if day_slot.slot_code:
            code = day_slot.slot_code
        else:
            # very simple pattern: use day_key + slot_number, e.g. 'mon1'
            code = f"{day_key}{day_slot.slot_number}"

        time_str = f"{day_slot.start_time.strftime('%H:%M')}-{day_slot.end_time.strftime('%H:%M')}"
        slots_by_day[day_key][code] = time_str

    return slots_by_day


def build_teachers_payload(timetable: Timetable) -> List[Dict[str, Any]]:
    """
    Build list of teacher dicts for optimisation.

    - We read User objects with role=TEACHER
    - We read TeacherSlotAvailability for this timetable to know which
      slot codes are allowed for each teacher.
    """

    teachers_qs = User.objects.filter(role=User.ROLE_TEACHER).order_by("id")

    # teacher_id -> set(slot_code)
    teacher_slots: Dict[int, List[str]] = {}

    avail_qs = (
        TeacherSlotAvailability.objects.filter(
            timetable=timetable,
            is_available=True,
        )
        .select_related("teacher", "day_slot")
        .order_by("teacher_id", "day_slot__day", "day_slot__slot_number")
    )

    for av in avail_qs:
        day_key = DAY_MAP_SHORT[av.day_slot.day]
        code = av.day_slot.slot_code or f"{day_key}{av.day_slot.slot_number}"
        teacher_slots.setdefault(av.teacher_id, []).append(code)

    payload: List[Dict[str, Any]] = []
    for teacher in teachers_qs:
        available_slots = teacher_slots.get(teacher.id, [])
        payload.append(
            {
                "Employ-id": teacher.teacher_employee_id or teacher.id,
                "Name": teacher.get_full_name() or teacher.username,
                "Code": teacher.teacher_code or teacher.username,
                "subjects": teacher.teacher_subjects or "",
                "avilable_slots": available_slots,
            }
        )

    return payload


def build_batches_payload(timetable: Timetable) -> Dict[str, Dict[str, Any]]:
    """
    Build BATCHES-like dict from BatchFacultyLoad rows.

    Output shape:
    {
      "HDTN-1A-ZA1": {
         "sub_teachers": [
             {
                 "teacher": "PVS",
                 "min_class": 8,
                 "max_class": 9,
                 "min_class_day": 1,
                 "max_class_day": 2,
             },
             ...
         ]
      },
      ...
    }
    """

    loads = (
        BatchFacultyLoad.objects.filter(timetable=timetable)
        .select_related("batch", "teacher")
        .order_by("batch__code", "teacher__teacher_code")
    )

    batches: Dict[str, Dict[str, Any]] = {}

    for load in loads:
        batch_code = load.batch.code
        teacher_code = load.teacher.teacher_code or load.teacher.username

        batches.setdefault(batch_code, {"sub_teachers": []})
        # Extract subject from teacher's subjects or use a default
        teacher_subjects = load.teacher.teacher_subjects or ""
        subjects_list = [s.strip() for s in teacher_subjects.split(",") if s.strip()] if teacher_subjects else []
        # Use first subject or create a default based on teacher code
        subject = subjects_list[0] if subjects_list else f"Subject_{teacher_code}"
        
        batches[batch_code]["sub_teachers"].append(
            {
                "teacher": teacher_code,
                "subject": subject,  # Add subject to payload
                "min_class": int(load.total_lectures),  # total per period
                "max_class": int(load.max_lectures_per_week or load.total_lectures),  # Use max_lectures_per_week if available
                "min_class_day": float(load.min_lectures_per_day),
                "max_class_day": float(load.max_lectures_per_day),
            }
        )

    return batches


def build_fixed_slots_payload(
    timetable: Timetable,
) -> Dict[str, Dict[str, Dict[str, Optional[Tuple[str, str]]]]]:
    """
    Build fixed_slots dict from FixedSlot rows.

    Shape:
      fixed_slots[day_key][slot_code][batch_code] = (subject, teacher_code) or None
    """

    fixed_qs = (
        FixedSlot.objects.filter(timetable=timetable, is_locked=True)
        .select_related("day_slot", "batch", "teacher")
        .order_by("day_slot__day", "day_slot__slot_number", "batch__code")
    )

    result: Dict[str, Dict[str, Dict[str, Optional[Tuple[str, str]]]]] = {}

    for fs in fixed_qs:
        day_key = DAY_MAP_SHORT[fs.day_slot.day]
        slot_code = fs.day_slot.slot_code or f"{day_key}{fs.day_slot.slot_number}"
        batch_code = fs.batch.code

        result.setdefault(day_key, {})
        result[day_key].setdefault(slot_code, {})

        if fs.subject and fs.teacher:
            value: Optional[Tuple[str, str]] = (
                fs.subject,
                fs.teacher.teacher_code or fs.teacher.username,
            )
        else:
            value = None

        result[day_key][slot_code][batch_code] = value

    return result


def build_full_payload(timetable_id: str) -> Dict[str, Any]:
    """
    Convenience helper used by the API view.

    Returns a single JSON-serialisable dict:
    {
      "available_slots": {...},
      "teachers": [...],
      "batches": {...},
      "fixed_slots": {...},
    }
    """

    timetable = Timetable.objects.get(id=timetable_id)

    return {
        "available_slots": build_available_slots(timetable),
        "teachers": build_teachers_payload(timetable),
        "batches": build_batches_payload(timetable),
        "fixed_slots": build_fixed_slots_payload(timetable),
    }

"""
Pure Python helper classes and functions used by timetable optimisation code.

These are **not** Django models. They are small, reusable data structures
that make it easy to:

- Build `available_slots` dictionaries for algorithms
- Build `fixed_slots` dictionaries
- Represent teachers in the exact shape your optimisation code expects

Nothing in this file hits the database directly. You can import these
from views/DRF/management commands and feed them with ORM query results.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import (
    Timetable,
    DaySlot,
    TimetableEntry,
    TeacherSlotAvailability,
    FixedSlot,
)
from accounts.models import User


@dataclass
class TeacherDTO:
    """
    Lightweight representation of a teacher for optimisation code.

    Attributes mirror your example:
    - name
    - code
    - employ_id
    - subject
    - available_slots: a flat list of slot codes like:
      ['m1', 'm2', 'm3', 'm4', 'm5', 'tu3', 'tu4', ...]
    """

    name: str
    code: str
    employ_id: str
    subject: str
    available_slots: List[str] = field(default_factory=list)

    def update_available_slots(self, available_slots: List[str]) -> None:
        """Update in-memory available slots list."""
        self.available_slots = available_slots


def build_available_slots_dict(timetable: Timetable) -> Dict[str, Dict[str, str]]:
    """
    Build a nested dictionary similar to your `available_slots` example:

    {
        'mon': {'m1': '08:00-09:30', 'm2': '09:40-11:10', ...},
        'tue': {...},
        ...
    }

    Day keys use lowercase short names:
    - 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'
    Slot keys use `DaySlot.slot_code`.
    """

    day_map = {
        DaySlot.MONDAY: "mon",
        DaySlot.TUESDAY: "tue",
        DaySlot.WEDNESDAY: "wed",
        DaySlot.THURSDAY: "thu",
        DaySlot.FRIDAY: "fri",
        DaySlot.SATURDAY: "sat",
        DaySlot.SUNDAY: "sun",
    }

    result: Dict[str, Dict[str, str]] = {}
    slots = timetable.day_slots.all().order_by("day", "slot_number")

    for slot in slots:
        day_key = day_map[slot.day]
        if day_key not in result:
            result[day_key] = {}
        code = slot.slot_code or f"{day_key}{slot.slot_number}"
        result[day_key][code] = f"{slot.start_time.strftime('%H:%M')}-{slot.end_time.strftime('%H:%M')}"

    return result


def build_teachers_dict(
    timetable: Timetable,
    teachers_qs,
) -> Dict[str, TeacherDTO]:
    """
    Build a dictionary like:

        teachers = {
            't1': TeacherDTO(...),
            't2': TeacherDTO(...),
            ...
        }

    Availability is taken from `TeacherSlotAvailability` for that timetable.
    """

    # Preload all availability rows into a mapping:
    # teacher_id -> list of allowed slot codes.
    availabilities = TeacherSlotAvailability.objects.filter(
        timetable=timetable, is_available=True
    ).select_related("teacher", "day_slot")

    teacher_to_slots: Dict[int, List[str]] = {}
    day_map = {
        DaySlot.MONDAY: "mon",
        DaySlot.TUESDAY: "tue",
        DaySlot.WEDNESDAY: "wed",
        DaySlot.THURSDAY: "thu",
        DaySlot.FRIDAY: "fri",
        DaySlot.SATURDAY: "sat",
        DaySlot.SUNDAY: "sun",
    }

    for av in availabilities:
        day_key = day_map[av.day_slot.day]
        code = av.day_slot.slot_code or f"{day_key}{av.day_slot.slot_number}"
        teacher_to_slots.setdefault(av.teacher_id, []).append(code)

    teachers_dict: Dict[str, TeacherDTO] = {}
    for idx, teacher in enumerate(teachers_qs, start=1):
        if not isinstance(teacher, User):
            continue

        key = f"t{idx}"
        available_codes = teacher_to_slots.get(teacher.id, [])
        dto = TeacherDTO(
            name=teacher.get_full_name() or teacher.username,
            code=teacher.teacher_code or "",
            employ_id=teacher.teacher_employee_id or "",
            subject=teacher.teacher_subjects or "",
            available_slots=available_codes,
        )
        teachers_dict[key] = dto

    return teachers_dict


def build_fixed_slots_dict(
    timetable: Timetable,
) -> Dict[str, Dict[str, Dict[str, Optional[Tuple[str, str]]]]]:
    """
    Build a nested dictionary similar to your `fixed_slots` structure:

        fixed_slots[day_key][slot_code][batch_code] = (subject, teacher_code) or None

    - day_key: 'mon', 'tue', ... (lowercase)
    - slot_code: DaySlot.slot_code (e.g. 'm1', 'tu3')
    - batch_code: Batch.code
    - value: (subject, teacher_code) or None if free / exam / other
    """

    day_map = {
        DaySlot.MONDAY: "mon",
        DaySlot.TUESDAY: "tue",
        DaySlot.WEDNESDAY: "wed",
        DaySlot.THURSDAY: "thu",
        DaySlot.FRIDAY: "fri",
        DaySlot.SATURDAY: "sat",
        DaySlot.SUNDAY: "sun",
    }

    result: Dict[str, Dict[str, Dict[str, Optional[Tuple[str, str]]]]] = {}

    qs = (
        FixedSlot.objects.filter(timetable=timetable, is_locked=True)
        .select_related("day_slot", "batch", "teacher")
        .order_by("day_slot__day", "day_slot__slot_number", "batch__code")
    )

    for fs in qs:
        day_key = day_map[fs.day_slot.day]
        slot_code = fs.day_slot.slot_code or f"{day_key}{fs.day_slot.slot_number}"
        batch_code = fs.batch.code

        if day_key not in result:
            result[day_key] = {}
        if slot_code not in result[day_key]:
            result[day_key][slot_code] = {}

        if fs.subject and fs.teacher:
            value: Optional[Tuple[str, str]] = (
                fs.subject,
                fs.teacher.teacher_code or "",
            )
        else:
            # None means fixed as FREE / EXAM etc.
            value = None

        result[day_key][slot_code][batch_code] = value

    return result


