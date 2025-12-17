from __future__ import annotations

"""
Simple JSON APIs to expose timetable data for the optimisation code.

These views do NOT implement the optimisation algorithm themselves.
They only:
1) Read from Django models
2) Build plain Python dicts/lists in the shapes your Python code expects
3) Return them as JSON so you can plug them directly into your optimiser
"""

from django.http import JsonResponse, Http404
from django.views.decorators.http import require_GET
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime

from accounts.models import Center, Batch, User as AccountUser
from .optimization import build_full_payload
from .models import Timetable, DaySlot, TimetableHoliday, TeacherSlotAvailability, BatchFacultyLoad, FixedSlot


@require_GET
def timetable_payload(request, timetable_id: str):
    """
    GET /api/timetables/<timetable_id>/payload/

    Returns JSON:
    {
      "available_slots": {...},
      "teachers": [...],
      "batches": {...},
      "fixed_slots": {...}
    }

    You can feed this directly to your optimisation code
    instead of reading from Excel.
    """

    try:
        payload = build_full_payload(timetable_id)
    except Exception as exc:  # pragma: no cover - simple error wrapper
        raise Http404(str(exc))

    return JsonResponse(payload, json_dumps_params={"indent": 2})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_timetable_with_slots(request):
    """
    Create a Timetable with weekly slots and holidays.

    Allowed roles:
    - ADMIN (center admins): center is taken from request.user.center
    - SUPER_ADMIN: must provide center_name in payload

    Example payload:
    {
      "center_name": "Allen - Jaipur Center",  # required only for SUPER_ADMIN
      "from_date": "2025-01-01",
      "to_date": "2025-03-31",
      "free_classes_count": 3,
      "weekly_slots": {
        "mon": [
          {"code": "m1", "start": "08:00", "end": "09:30", "is_free_class": false},
          {"code": "m2", "start": "09:40", "end": "11:10", "is_free_class": false}
        ],
        "tue": [
          {"code": "tu1", "start": "08:00", "end": "09:30", "is_free_class": false}
        ]
      },
      "holidays": [
        {"date": "2025-01-26", "description": "Republic Day"},
        {"date": "2025-03-08", "description": "Internal Exam"}
      ]
    }
    """

    user = request.user
    if user.role not in (AccountUser.ROLE_ADMIN, AccountUser.ROLE_SUPER_ADMIN):
        return Response(
            {"detail": "Only Admin or Super Admin can create timetables."},
            status=status.HTTP_403_FORBIDDEN,
        )

    data = request.data

    center = None
    if user.role == AccountUser.ROLE_ADMIN:
        center = user.center
        if not center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    else:  # SUPER_ADMIN
        center_name = data.get("center_name")
        if not center_name:
            return Response(
                {"detail": "center_name is required for Super Admin."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            center = Center.objects.get(name=center_name)
        except Center.DoesNotExist:
            return Response(
                {"detail": f"Center '{center_name}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Center.MultipleObjectsReturned:
            return Response(
                {
                    "detail": (
                        f"Multiple centers found with name '{center_name}'. "
                        "Please use a more specific name or handle via center_id."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    from_date_str = data.get("from_date")
    to_date_str = data.get("to_date")
    free_classes_count = data.get("free_classes_count", 0)
    weekly_slots = data.get("weekly_slots", {})
    holidays = data.get("holidays", [])

    if not from_date_str or not to_date_str:
        return Response(
            {"detail": "from_date and to_date are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()
    except ValueError:
        return Response(
            {"detail": "from_date and to_date must be in YYYY-MM-DD format."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if from_date > to_date:
        return Response(
            {"detail": "from_date cannot be after to_date."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Create timetable
    timetable = Timetable.objects.create(
        center=center,
        from_date=from_date,
        to_date=to_date,
        free_classes_count=free_classes_count,
        description=data.get("description", ""),
    )

    # Map day keys to DaySlot constants
    day_map = {
        "mon": DaySlot.MONDAY,
        "tue": DaySlot.TUESDAY,
        "wed": DaySlot.WEDNESDAY,
        "thu": DaySlot.THURSDAY,
        "fri": DaySlot.FRIDAY,
        "sat": DaySlot.SATURDAY,
        "sun": DaySlot.SUNDAY,
    }

    created_slots = 0
    for day_key, slots in weekly_slots.items():
        day_const = day_map.get(day_key.lower())
        if not day_const:
            continue

        slot_number = 0
        for slot in slots:
            slot_number += 1
            code = slot.get("code") or f"{day_key}{slot_number}"
            start_str = slot.get("start")
            end_str = slot.get("end")
            is_free = bool(slot.get("is_free_class", False))

            if not start_str or not end_str:
                continue

            try:
                start_time = datetime.strptime(start_str, "%H:%M").time()
                end_time = datetime.strptime(end_str, "%H:%M").time()
            except ValueError:
                continue

            DaySlot.objects.create(
                timetable=timetable,
                day=day_const,
                slot_code=code,
                slot_number=slot_number,
                start_time=start_time,
                end_time=end_time,
                is_free_class=is_free,
            )
            created_slots += 1

    # Create holidays
    created_holidays = 0
    for h in holidays:
        date_str = h.get("date")
        description = h.get("description", "")
        if not date_str:
            continue
        try:
            h_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        TimetableHoliday.objects.create(
            timetable=timetable,
            date=h_date,
            description=description,
            is_full_day=True,
        )
        created_holidays += 1

    return Response(
        {
            "message": "Timetable created successfully.",
            "timetable_id": str(timetable.id),
            "center": center.name,
            "from_date": str(from_date),
            "to_date": str(to_date),
            "slots_created": created_slots,
            "holidays_created": created_holidays,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_timetable(request, timetable_id: str):
    """
    Get timetable details by ID.
    
    GET /api/timetables/<timetable_id>/
    
    Returns:
    {
      "id": "uuid",
      "center": "Allen - Jaipur Center",
      "from_date": "2025-01-01",
      "to_date": "2025-03-31",
      "free_classes_count": 3,
      "is_active": true,
      "description": "...",
      "created_at": "...",
      "updated_at": "..."
    }
    """
    try:
        timetable = Timetable.objects.get(id=timetable_id)
    except Timetable.DoesNotExist:
        return Response(
            {"detail": "Timetable not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions: Admin can only see their center's timetables
    user = request.user
    if user.role == AccountUser.ROLE_ADMIN:
        if user.center != timetable.center:
            return Response(
                {"detail": "You don't have permission to view this timetable."},
                status=status.HTTP_403_FORBIDDEN,
            )
    
    return Response(
        {
            "id": str(timetable.id),
            "center": timetable.center.name,
            "center_id": str(timetable.center.id),
            "from_date": str(timetable.from_date),
            "to_date": str(timetable.to_date),
            "free_classes_count": timetable.free_classes_count,
            "is_active": timetable.is_active,
            "description": timetable.description,
            "created_at": timetable.created_at.isoformat(),
            "updated_at": timetable.updated_at.isoformat(),
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_timetable_slots(request, timetable_id: str):
    """
    Get all slots for a timetable, organized by day.
    
    GET /api/timetables/<timetable_id>/slots/
    
    Returns:
    {
      "timetable_id": "uuid",
      "timetable": "Allen - Jaipur Center - 2025-01-01 to 2025-03-31",
      "slots": {
        "mon": [
          {
            "id": "uuid",
            "code": "m1",
            "slot_number": 1,
            "start_time": "08:00",
            "end_time": "09:30",
            "is_free_class": false
          },
          ...
        ],
        "tue": [...],
        ...
      },
      "total_slots": 10
    }
    """
    try:
        timetable = Timetable.objects.get(id=timetable_id)
    except Timetable.DoesNotExist:
        return Response(
            {"detail": "Timetable not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions
    user = request.user
    if user.role == AccountUser.ROLE_ADMIN:
        if user.center != timetable.center:
            return Response(
                {"detail": "You don't have permission to view this timetable."},
                status=status.HTTP_403_FORBIDDEN,
            )
    
    # Get all slots for this timetable
    day_slots = DaySlot.objects.filter(timetable=timetable).order_by("day", "slot_number")
    
    # Organize by day
    slots_by_day = {
        "mon": [],
        "tue": [],
        "wed": [],
        "thu": [],
        "fri": [],
        "sat": [],
        "sun": [],
    }
    
    day_key_map = {
        DaySlot.MONDAY: "mon",
        DaySlot.TUESDAY: "tue",
        DaySlot.WEDNESDAY: "wed",
        DaySlot.THURSDAY: "thu",
        DaySlot.FRIDAY: "fri",
        DaySlot.SATURDAY: "sat",
        DaySlot.SUNDAY: "sun",
    }
    
    total_slots = 0
    for slot in day_slots:
        day_key = day_key_map.get(slot.day)
        if day_key:
            slots_by_day[day_key].append({
                "id": str(slot.id),
                "code": slot.slot_code,
                "slot_number": slot.slot_number,
                "start_time": slot.start_time.strftime("%H:%M"),
                "end_time": slot.end_time.strftime("%H:%M"),
                "is_free_class": slot.is_free_class,
            })
            total_slots += 1
    
    return Response(
        {
            "timetable_id": str(timetable.id),
            "timetable": str(timetable),
            "from_date": str(timetable.from_date),
            "to_date": str(timetable.to_date),
            "slots": slots_by_day,
            "total_slots": total_slots,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_timetables(request):
    """
    List all timetables (filtered by center for Admin).
    
    GET /api/timetables/
    GET /api/timetables/?center_name=Allen - Jaipur Center  (for Super Admin)
    
    Returns:
    {
      "timetables": [
        {
          "id": "uuid",
          "center": "Allen - Jaipur Center",
          "from_date": "2025-01-01",
          "to_date": "2025-03-31",
          "is_active": true,
          "slots_count": 10,
          "holidays_count": 2
        },
        ...
      ],
      "total": 5
    }
    """
    user = request.user
    
    # Filter by center based on role
    if user.role == AccountUser.ROLE_ADMIN:
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        timetables = Timetable.objects.filter(center=user.center)
    elif user.role == AccountUser.ROLE_SUPER_ADMIN:
        # Super Admin can filter by center_name or see all
        center_name = request.query_params.get("center_name")
        if center_name:
            try:
                center = Center.objects.get(name=center_name)
                timetables = Timetable.objects.filter(center=center)
            except Center.DoesNotExist:
                return Response(
                    {"detail": f"Center '{center_name}' not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            timetables = Timetable.objects.all()
    else:
        return Response(
            {"detail": "You don't have permission to view timetables."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    # Order by date (newest first)
    timetables = timetables.order_by("-from_date", "-to_date")
    
    # Build response
    timetable_list = []
    for tt in timetables:
        slots_count = DaySlot.objects.filter(timetable=tt).count()
        holidays_count = TimetableHoliday.objects.filter(timetable=tt).count()
        
        timetable_list.append({
            "id": str(tt.id),
            "center": tt.center.name,
            "from_date": str(tt.from_date),
            "to_date": str(tt.to_date),
            "free_classes_count": tt.free_classes_count,
            "is_active": tt.is_active,
            "description": tt.description,
            "slots_count": slots_count,
            "holidays_count": holidays_count,
            "created_at": tt.created_at.isoformat(),
        })
    
    return Response(
        {
            "timetables": timetable_list,
            "total": len(timetable_list),
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def set_teacher_slot_availability(request):
    """
    Admin sets teacher availability for a specific slot in a timetable.
    
    By default, teachers are available. Admin can toggle availability.
    When a teacher is marked as available in one timetable for a slot,
    they become unavailable for the same time slot in other overlapping timetables
    within the same center.
    
    Payload:
    {
        "timetable_id": "uuid",
        "day_slot_id": "uuid",
        "teacher_code": "AK-CAP",  # or teacher username/email
        "is_available": true  # or false
    }
    
    Returns:
    {
        "message": "Teacher availability updated successfully.",
        "teacher": "AK-CAP",
        "slot_code": "m1",
        "day": "Monday",
        "is_available": true
    }
    """
    user = request.user
    
    # Check if user is Admin or Super Admin
    if user.role not in (AccountUser.ROLE_ADMIN, AccountUser.ROLE_SUPER_ADMIN):
        return Response(
            {"detail": "Only Admin and Super Admin can set teacher availability."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    # If Admin, ensure they can only manage their center's timetables
    if user.role == AccountUser.ROLE_ADMIN:
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    
    timetable_id = request.data.get("timetable_id")
    day_slot_id = request.data.get("day_slot_id")
    teacher_identifier = request.data.get("teacher_code") or request.data.get("teacher_username") or request.data.get("teacher_email")
    is_available = request.data.get("is_available")
    
    if not timetable_id or not day_slot_id or not teacher_identifier:
        return Response(
            {"detail": "timetable_id, day_slot_id, and teacher_code/username/email are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    if is_available is None:
        return Response(
            {"detail": "is_available (true/false) is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Get timetable
    try:
        timetable = Timetable.objects.select_related("center").get(id=timetable_id)
    except Timetable.DoesNotExist:
        return Response(
            {"detail": "Timetable not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions: Admin can only manage their center's timetables
    if user.role == AccountUser.ROLE_ADMIN:
        if timetable.center != user.center:
            return Response(
                {"detail": "You can only manage timetables in your center."},
                status=status.HTTP_403_FORBIDDEN,
            )
    
    # Get day slot
    try:
        day_slot = DaySlot.objects.get(id=day_slot_id, timetable=timetable)
    except DaySlot.DoesNotExist:
        return Response(
            {"detail": "Day slot not found in this timetable."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Get teacher
    try:
        from django.db.models import Q
        teacher = AccountUser.objects.get(
            Q(role=AccountUser.ROLE_TEACHER) &
            (Q(teacher_code__iexact=teacher_identifier) |
             Q(username__iexact=teacher_identifier) |
             Q(email__iexact=teacher_identifier))
        )
    except AccountUser.DoesNotExist:
        return Response(
            {"detail": f"Teacher with code/username/email '{teacher_identifier}' not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except AccountUser.MultipleObjectsReturned:
        return Response(
            {"detail": f"Multiple teachers found with identifier '{teacher_identifier}'. Please use teacher_code."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Create or update TeacherSlotAvailability
    try:
        from django.db import transaction
        with transaction.atomic():
            availability, created = TeacherSlotAvailability.objects.get_or_create(
                timetable=timetable,
                teacher=teacher,
                day_slot=day_slot,
                defaults={"is_available": is_available}
            )
            
            if not created:
                availability.is_available = is_available
                # Call full_clean to trigger validation
                availability.full_clean()
                availability.save()
            
            # Map day constant to display name
            day_display_map = {
                DaySlot.MONDAY: "Monday",
                DaySlot.TUESDAY: "Tuesday",
                DaySlot.WEDNESDAY: "Wednesday",
                DaySlot.THURSDAY: "Thursday",
                DaySlot.FRIDAY: "Friday",
                DaySlot.SATURDAY: "Saturday",
                DaySlot.SUNDAY: "Sunday",
            }
            
            return Response(
                {
                    "message": "Teacher availability updated successfully.",
                    "teacher": teacher.teacher_code or teacher.username,
                    "teacher_name": f"{teacher.first_name} {teacher.last_name}".strip(),
                    "slot_code": day_slot.slot_code,
                    "day": day_display_map.get(day_slot.day, day_slot.day),
                    "start_time": str(day_slot.start_time),
                    "end_time": str(day_slot.end_time),
                    "is_available": availability.is_available,
                },
                status=status.HTTP_200_OK,
            )
    except Exception as e:
        # Check if it's a ValidationError from clean()
        from django.core.exceptions import ValidationError
        if isinstance(e, ValidationError):
            return Response(
                {"detail": str(e.message_dict.get("is_available", [str(e)])[0])},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"detail": f"Error updating teacher availability: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_teacher_availability(request, timetable_id: str):
    """
    Get teacher availability for all slots in a timetable.
    
    Returns availability organized by slot code, showing which teachers
    are available/unavailable for each slot.
    
    Returns:
    {
        "timetable_id": "uuid",
        "timetable": "Center Name - 2025-01-01 to 2025-03-31",
        "slots": [
            {
                "slot_id": "uuid",
                "slot_code": "m1",
                "day": "Monday",
                "start_time": "08:00:00",
                "end_time": "09:30:00",
                "teachers": [
                    {
                        "teacher_code": "AK-CAP",
                        "teacher_name": "A K",
                        "is_available": true
                    }
                ]
            }
        ]
    }
    """
    user = request.user
    
    # Check if user is Admin or Super Admin
    if user.role not in (AccountUser.ROLE_ADMIN, AccountUser.ROLE_SUPER_ADMIN):
        return Response(
            {"detail": "Only Admin and Super Admin can view teacher availability."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    # Get timetable
    try:
        timetable = Timetable.objects.select_related("center").get(id=timetable_id)
    except Timetable.DoesNotExist:
        return Response(
            {"detail": "Timetable not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions: Admin can only view their center's timetables
    if user.role == AccountUser.ROLE_ADMIN:
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if timetable.center != user.center:
            return Response(
                {"detail": "You can only view timetables in your center."},
                status=status.HTTP_403_FORBIDDEN,
            )
    
    # Get all day slots for this timetable
    day_slots = DaySlot.objects.filter(timetable=timetable).order_by("day", "slot_number")
    
    # Get all teachers in the center
    center = timetable.center
    teachers = AccountUser.objects.filter(
        role=AccountUser.ROLE_TEACHER,
        center=center
    ).order_by("teacher_code", "username")
    
    # Get all teacher slot availabilities for this timetable
    availabilities = TeacherSlotAvailability.objects.filter(
        timetable=timetable
    ).select_related("teacher", "day_slot")
    
    # Create a map: (day_slot_id, teacher_id) -> is_available
    availability_map = {}
    for av in availabilities:
        key = (av.day_slot_id, av.teacher_id)
        availability_map[key] = av.is_available
    
    # Map day constant to display name
    day_display_map = {
        DaySlot.MONDAY: "Monday",
        DaySlot.TUESDAY: "Tuesday",
        DaySlot.WEDNESDAY: "Wednesday",
        DaySlot.THURSDAY: "Thursday",
        DaySlot.FRIDAY: "Friday",
        DaySlot.SATURDAY: "Saturday",
        DaySlot.SUNDAY: "Sunday",
    }
    
    # Build response
    slots_data = []
    for slot in day_slots:
        teachers_data = []
        for teacher in teachers:
            # Default is available (True) if not explicitly set
            key = (slot.id, teacher.id)
            is_available = availability_map.get(key, True)
            
            teachers_data.append({
                "teacher_code": teacher.teacher_code or teacher.username,
                "teacher_name": f"{teacher.first_name} {teacher.last_name}".strip() or teacher.username,
                "teacher_id": str(teacher.id),
                "is_available": is_available,
            })
        
        slots_data.append({
            "slot_id": str(slot.id),
            "slot_code": slot.slot_code,
            "day": day_display_map.get(slot.day, slot.day),
            "start_time": str(slot.start_time),
            "end_time": str(slot.end_time),
            "is_free_class": slot.is_free_class,
            "teachers": teachers_data,
        })
    
    return Response(
        {
            "timetable_id": str(timetable.id),
            "timetable": str(timetable),
            "center": timetable.center.name,
            "from_date": str(timetable.from_date),
            "to_date": str(timetable.to_date),
            "slots": slots_data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def assign_batch_to_timetable(request):
    """
    Admin assigns a batch to a timetable.
    This makes the batch available for all slots in the timetable.
    
    Payload:
    {
        "timetable_id": "uuid",
        "batch_code": "HDTN-1A-ZA1"
    }
    
    Returns:
    {
        "message": "Batch assigned to timetable successfully.",
        "timetable_id": "uuid",
        "batch_code": "HDTN-1A-ZA1",
        "batch_name": "Super 30 - Batch A (2025)"
    }
    """
    user = request.user
    
    # Check if user is Admin or Super Admin
    if user.role not in (AccountUser.ROLE_ADMIN, AccountUser.ROLE_SUPER_ADMIN):
        return Response(
            {"detail": "Only Admin and Super Admin can assign batches to timetables."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    timetable_id = request.data.get("timetable_id")
    batch_code = request.data.get("batch_code")
    
    if not timetable_id or not batch_code:
        return Response(
            {"detail": "timetable_id and batch_code are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Get timetable
    try:
        timetable = Timetable.objects.select_related("center").get(id=timetable_id)
    except Timetable.DoesNotExist:
        return Response(
            {"detail": "Timetable not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions: Admin can only manage their center's timetables
    if user.role == AccountUser.ROLE_ADMIN:
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if timetable.center != user.center:
            return Response(
                {"detail": "You can only manage timetables in your center."},
                status=status.HTTP_403_FORBIDDEN,
            )
    
    # Get batch
    try:
        batch = Batch.objects.select_related("program", "program__center").get(code=batch_code)
    except Batch.DoesNotExist:
        return Response(
            {"detail": f"Batch with code '{batch_code}' not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Verify batch belongs to the same center as timetable
    if batch.program.center != timetable.center:
        return Response(
            {"detail": f"Batch '{batch_code}' does not belong to the same center as the timetable."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Check if batch is already assigned (by checking if any BatchFacultyLoad exists)
    # This is just a check - we don't create BatchFacultyLoad here, only when teachers are assigned
    # But we can return success if batch is already in use
    
    return Response(
        {
            "message": "Batch assigned to timetable successfully. You can now assign teachers to this batch.",
            "timetable_id": str(timetable.id),
            "batch_code": batch.code,
            "batch_name": batch.name,
            "batch_id": str(batch.id),
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def assign_teacher_to_batch(request):
    """
    Admin assigns a teacher to a batch in a timetable with lecture constraints.
    Subject is automatically taken from teacher's teacher_subjects field.
    
    Values are batch-specific: Each batch-teacher combination has its own values.
    If the same teacher is added to a different batch, admin must provide new values.
    
    Payload:
    {
        "timetable_id": "uuid",
        "batch_code": "HDTN-1A-ZA1",
        "teacher_code": "AK-CAP",
        "min_lectures_per_day": 1,
        "max_lectures_per_day": 2,
        "max_lectures_per_week": 10,
        "total_lectures": 20
    }
    
    Returns:
    {
        "message": "Teacher assigned to batch successfully.",
        "teacher_code": "AK-CAP",
        "teacher_name": "A K",
        "subject": "Physics",
        "batch_code": "HDTN-1A-ZA1",
        "min_lectures_per_day": 1,
        "max_lectures_per_day": 2,
        "max_lectures_per_week": 10,
        "total_lectures": 20
    }
    """
    user = request.user
    
    # Check if user is Admin or Super Admin
    if user.role not in (AccountUser.ROLE_ADMIN, AccountUser.ROLE_SUPER_ADMIN):
        return Response(
            {"detail": "Only Admin and Super Admin can assign teachers to batches."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    timetable_id = request.data.get("timetable_id")
    batch_code = request.data.get("batch_code")
    teacher_code = request.data.get("teacher_code")
    
    # Get values from request, default to 0 if not provided
    min_lectures_per_day = request.data.get("min_lectures_per_day", 0)
    max_lectures_per_day = request.data.get("max_lectures_per_day", 0)
    max_lectures_per_week = request.data.get("max_lectures_per_week", 0)
    total_lectures = request.data.get("total_lectures", 0)  # Default to 0
    
    if not timetable_id or not batch_code or not teacher_code:
        return Response(
            {"detail": "timetable_id, batch_code, and teacher_code are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Get timetable
    try:
        timetable = Timetable.objects.select_related("center").get(id=timetable_id)
    except Timetable.DoesNotExist:
        return Response(
            {"detail": "Timetable not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions: Admin can only manage their center's timetables
    if user.role == AccountUser.ROLE_ADMIN:
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if timetable.center != user.center:
            return Response(
                {"detail": "You can only manage timetables in your center."},
                status=status.HTTP_403_FORBIDDEN,
            )
    
    # Get batch
    try:
        batch = Batch.objects.select_related("program", "program__center").get(code=batch_code)
    except Batch.DoesNotExist:
        return Response(
            {"detail": f"Batch with code '{batch_code}' not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Verify batch belongs to the same center as timetable
    if batch.program.center != timetable.center:
        return Response(
            {"detail": f"Batch '{batch_code}' does not belong to the same center as the timetable."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Handle FREE teacher (special case)
    is_free_teacher = teacher_code.upper().startswith("FREE")
    teacher = None
    
    if is_free_teacher:
        # For FREE teachers, create or get a special teacher user
        # FREE, FREE1, FREE2, etc. are all valid
        free_code = teacher_code.upper()  # Normalize to uppercase
        
        # Try to find existing FREE teacher in this center
        from django.db.models import Q
        try:
            teacher = AccountUser.objects.get(
                role=AccountUser.ROLE_TEACHER,
                center=timetable.center,
                teacher_code__iexact=free_code
            )
        except AccountUser.DoesNotExist:
            # Create new FREE teacher
            teacher = AccountUser.objects.create_user(
                username=free_code,
                teacher_code=free_code,
                role=AccountUser.ROLE_TEACHER,
                center=timetable.center,
                first_name="FREE",
                last_name=free_code.replace("FREE", "").strip() or "",
                teacher_subjects="FREE",
                password="FREE_TEACHER_PLACEHOLDER",  # Placeholder password, not used for login
            )
        except AccountUser.MultipleObjectsReturned:
            # If multiple found, use the first one
            teacher = AccountUser.objects.filter(
                role=AccountUser.ROLE_TEACHER,
                center=timetable.center,
                teacher_code__iexact=free_code
            ).first()
        
        # Ensure teacher belongs to the same center
        if teacher.center != timetable.center:
            teacher.center = timetable.center
            teacher.save()
    else:
        # Get regular teacher
        try:
            from django.db.models import Q
            teacher = AccountUser.objects.get(
                Q(role=AccountUser.ROLE_TEACHER) &
                (Q(teacher_code__iexact=teacher_code) |
                 Q(username__iexact=teacher_code) |
                 Q(email__iexact=teacher_code))
            )
        except AccountUser.DoesNotExist:
            return Response(
                {"detail": f"Teacher with code '{teacher_code}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except AccountUser.MultipleObjectsReturned:
            return Response(
                {"detail": f"Multiple teachers found with code '{teacher_code}'. Please use unique teacher_code."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        # Verify teacher belongs to the same center
        if teacher.center != timetable.center:
            return Response(
                {"detail": f"Teacher '{teacher_code}' does not belong to the same center as the timetable."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    
    # Values are batch-specific - each batch-teacher combination has its own values
    # No need to copy from other batches or timetables
    
    # Validate lecture constraints
    if min_lectures_per_day < 0:
        return Response(
            {"detail": "min_lectures_per_day must be >= 0."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if max_lectures_per_day < 0:
        return Response(
            {"detail": "max_lectures_per_day must be >= 0."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if max_lectures_per_week < 0:
        return Response(
            {"detail": "max_lectures_per_week must be >= 0."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if min_lectures_per_day > max_lectures_per_day and max_lectures_per_day > 0:
        return Response(
            {"detail": "min_lectures_per_day cannot be greater than max_lectures_per_day."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if total_lectures < 0:
        return Response(
            {"detail": "total_lectures must be >= 0."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Create or update BatchFacultyLoad
    try:
        from django.db import transaction
        with transaction.atomic():
            faculty_load, created = BatchFacultyLoad.objects.update_or_create(
                timetable=timetable,
                teacher=teacher,
                batch=batch,
                defaults={
                    "min_lectures_per_day": min_lectures_per_day,
                    "max_lectures_per_day": max_lectures_per_day,
                    "max_lectures_per_week": max_lectures_per_week,
                    "total_lectures": total_lectures,
                }
            )
            
            # Get teacher's subject
            if is_free_teacher:
                subject = "FREE"
            else:
                subject = teacher.teacher_subjects or "Not specified"
            
            action = "created" if created else "updated"
            teacher_display_name = teacher.teacher_code or teacher.username
            if is_free_teacher:
                teacher_display_name = teacher.teacher_code  # FREE, FREE1, FREE2, etc.
            
            return Response(
                {
                    "message": f"{'FREE teacher' if is_free_teacher else 'Teacher'} assigned to batch successfully ({action}).",
                    "teacher_code": teacher_display_name,
                    "teacher_name": f"{teacher.first_name} {teacher.last_name}".strip() or teacher_display_name,
                    "teacher_id": str(teacher.id),
                    "subject": subject,
                    "is_free": is_free_teacher,
                    "batch_code": batch.code,
                    "batch_name": batch.name,
                    "min_lectures_per_day": faculty_load.min_lectures_per_day,
                    "max_lectures_per_day": faculty_load.max_lectures_per_day,
                    "max_lectures_per_week": faculty_load.max_lectures_per_week,
                    "total_lectures": faculty_load.total_lectures,
                },
                status=status.HTTP_200_OK,
            )
    except Exception as e:
        return Response(
            {"detail": f"Error assigning teacher to batch: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_timetable_batch_assignments(request, timetable_id: str):
    """
    Get all batch assignments and their teachers for a timetable.
    
    Returns:
    {
        "timetable_id": "uuid",
        "timetable": "Center Name - 2025-01-01 to 2025-03-31",
        "batches": [
            {
                "batch_code": "HDTN-1A-ZA1",
                "batch_name": "Super 30 - Batch A (2025)",
                "teachers": [
                    {
                        "teacher_code": "AK-CAP",
                        "teacher_name": "A K",
                        "subject": "Physics",
                        "min_lectures_per_day": 1,
                        "max_lectures_per_day": 3,
                        "total_lectures": 20,
                    }
                ]
            }
        ]
    }
    """
    user = request.user
    
    # Check if user is Admin or Super Admin
    if user.role not in (AccountUser.ROLE_ADMIN, AccountUser.ROLE_SUPER_ADMIN):
        return Response(
            {"detail": "Only Admin and Super Admin can view batch assignments."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    # Get timetable
    try:
        timetable = Timetable.objects.select_related("center").get(id=timetable_id)
    except Timetable.DoesNotExist:
        return Response(
            {"detail": "Timetable not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions: Admin can only view their center's timetables
    if user.role == AccountUser.ROLE_ADMIN:
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if timetable.center != user.center:
            return Response(
                {"detail": "You can only view timetables in your center."},
                status=status.HTTP_403_FORBIDDEN,
            )
    
    # Get all BatchFacultyLoad entries for this timetable
    faculty_loads = BatchFacultyLoad.objects.filter(
        timetable=timetable
    ).select_related("batch", "teacher").order_by("batch__code", "teacher__teacher_code", "teacher__username")
    
    # Group by batch
    batches_dict = {}
    for load in faculty_loads:
        batch_code = load.batch.code
        if batch_code not in batches_dict:
            batches_dict[batch_code] = {
                "batch_code": batch_code,
                "batch_name": load.batch.name,
                "batch_id": str(load.batch.id),
                "teachers": [],
            }
        
        # Check if this is a FREE teacher
        is_free = load.teacher.teacher_code and load.teacher.teacher_code.upper().startswith("FREE")
        
        if is_free:
            subject = "FREE"
        else:
            subject = load.teacher.teacher_subjects or "Not specified"
        
        teacher_code = load.teacher.teacher_code or load.teacher.username
        teacher_name = f"{load.teacher.first_name} {load.teacher.last_name}".strip() or teacher_code
        
        batches_dict[batch_code]["teachers"].append({
            "teacher_code": teacher_code,
            "teacher_name": teacher_name,
            "teacher_id": str(load.teacher.id),
            "subject": subject,
            "is_free": is_free,
            "min_lectures_per_day": load.min_lectures_per_day,
            "max_lectures_per_day": load.max_lectures_per_day,
            "max_lectures_per_week": load.max_lectures_per_week,
            "total_lectures": load.total_lectures,
        })
    
    batches_list = list(batches_dict.values())
    
    return Response(
        {
            "timetable_id": str(timetable.id),
            "timetable": str(timetable),
            "center": timetable.center.name,
            "from_date": str(timetable.from_date),
            "to_date": str(timetable.to_date),
            "batches": batches_list,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def assign_fixed_slot(request):
    """
    Admin assigns a teacher to a specific slot for a batch (fixed slot).
    This locks the slot so optimization cannot change it.
    
    Payload:
    {
        "timetable_id": "uuid",
        "slot_code": "m1",  # or day_slot_id
        "batch_code": "HDTN-1A-ZA1",
        "teacher_code": "AK-CAP",
        "subject": "Physics"  # Optional, will use teacher's subject if not provided
    }
    
    Returns:
    {
        "message": "Fixed slot assigned successfully.",
        "slot_code": "m1",
        "day": "Monday",
        "batch_code": "HDTN-1A-ZA1",
        "teacher_code": "AK-CAP",
        "subject": "Physics",
        "is_locked": true
    }
    """
    user = request.user
    
    # Check if user is Admin or Super Admin
    if user.role not in (AccountUser.ROLE_ADMIN, AccountUser.ROLE_SUPER_ADMIN):
        return Response(
            {"detail": "Only Admin and Super Admin can assign fixed slots."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    timetable_id = request.data.get("timetable_id")
    slot_code = request.data.get("slot_code")
    day_slot_id = request.data.get("day_slot_id")
    batch_code = request.data.get("batch_code")
    teacher_code = request.data.get("teacher_code")
    subject = request.data.get("subject", "")
    
    if not timetable_id or not batch_code:
        return Response(
            {"detail": "timetable_id and batch_code are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    if not slot_code and not day_slot_id:
        return Response(
            {"detail": "Either slot_code or day_slot_id is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Get timetable
    try:
        timetable = Timetable.objects.select_related("center").get(id=timetable_id)
    except Timetable.DoesNotExist:
        return Response(
            {"detail": "Timetable not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions: Admin can only manage their center's timetables
    if user.role == AccountUser.ROLE_ADMIN:
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if timetable.center != user.center:
            return Response(
                {"detail": "You can only manage timetables in your center."},
                status=status.HTTP_403_FORBIDDEN,
            )
    
    # Get day slot
    try:
        if day_slot_id:
            day_slot = DaySlot.objects.get(id=day_slot_id, timetable=timetable)
        else:
            day_slot = DaySlot.objects.get(slot_code=slot_code, timetable=timetable)
    except DaySlot.DoesNotExist:
        return Response(
            {"detail": f"Slot with code '{slot_code}' not found in this timetable."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except DaySlot.MultipleObjectsReturned:
        return Response(
            {"detail": f"Multiple slots found with code '{slot_code}'. Please use day_slot_id instead."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Get batch
    try:
        batch = Batch.objects.select_related("program", "program__center").get(code=batch_code)
    except Batch.DoesNotExist:
        return Response(
            {"detail": f"Batch with code '{batch_code}' not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Verify batch belongs to the same center as timetable
    if batch.program.center != timetable.center:
        return Response(
            {"detail": f"Batch '{batch_code}' does not belong to the same center as the timetable."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Get teacher (if provided)
    teacher = None
    if teacher_code:
        # Handle FREE teacher (special case)
        is_free_teacher = teacher_code.upper().startswith("FREE")
        
        if is_free_teacher:
            free_code = teacher_code.upper()
            try:
                teacher = AccountUser.objects.get(
                    role=AccountUser.ROLE_TEACHER,
                    center=timetable.center,
                    teacher_code__iexact=free_code
                )
            except AccountUser.DoesNotExist:
                # Create new FREE teacher
                teacher = AccountUser.objects.create_user(
                    username=free_code,
                    teacher_code=free_code,
                    role=AccountUser.ROLE_TEACHER,
                    center=timetable.center,
                    first_name="FREE",
                    last_name=free_code.replace("FREE", "").strip() or "",
                    teacher_subjects="FREE",
                    password="FREE_TEACHER_PLACEHOLDER",
                )
        else:
            try:
                from django.db.models import Q
                teacher = AccountUser.objects.get(
                    Q(role=AccountUser.ROLE_TEACHER) &
                    (Q(teacher_code__iexact=teacher_code) |
                     Q(username__iexact=teacher_code) |
                     Q(email__iexact=teacher_code))
                )
            except AccountUser.DoesNotExist:
                return Response(
                    {"detail": f"Teacher with code '{teacher_code}' not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            
            # Verify teacher belongs to the same center
            if teacher.center != timetable.center:
                return Response(
                    {"detail": f"Teacher '{teacher_code}' does not belong to the same center as the timetable."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        
        # If subject not provided, get from teacher
        if not subject and teacher:
            if is_free_teacher:
                subject = "FREE"
            else:
                subject = teacher.teacher_subjects or ""
    
    # Create or update FixedSlot
    try:
        from django.db import transaction
        with transaction.atomic():
            fixed_slot, created = FixedSlot.objects.update_or_create(
                timetable=timetable,
                day_slot=day_slot,
                batch=batch,
                defaults={
                    "teacher": teacher,
                    "subject": subject,
                    "is_locked": True,
                }
            )
            
            # Map day constant to display name
            day_display_map = {
                DaySlot.MONDAY: "Monday",
                DaySlot.TUESDAY: "Tuesday",
                DaySlot.WEDNESDAY: "Wednesday",
                DaySlot.THURSDAY: "Thursday",
                DaySlot.FRIDAY: "Friday",
                DaySlot.SATURDAY: "Saturday",
                DaySlot.SUNDAY: "Sunday",
            }
            
            action = "created" if created else "updated"
            return Response(
                {
                    "message": f"Fixed slot assigned successfully ({action}).",
                    "slot_code": day_slot.slot_code,
                    "day": day_display_map.get(day_slot.day, day_slot.day),
                    "start_time": str(day_slot.start_time),
                    "end_time": str(day_slot.end_time),
                    "batch_code": batch.code,
                    "batch_name": batch.name,
                    "teacher_code": teacher.teacher_code if teacher else None,
                    "teacher_name": f"{teacher.first_name} {teacher.last_name}".strip() if teacher else None,
                    "subject": subject or "Free / Exam",
                    "is_locked": fixed_slot.is_locked,
                },
                status=status.HTTP_200_OK,
            )
    except Exception as e:
        return Response(
            {"detail": f"Error assigning fixed slot: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_fixed_slots(request, timetable_id: str):
    """
    Get all fixed slots for a timetable.
    
    Returns:
    {
        "timetable_id": "uuid",
        "timetable": "Center Name - 2025-01-01 to 2025-03-31",
        "fixed_slots": [
            {
                "slot_code": "m1",
                "day": "Monday",
                "start_time": "08:00:00",
                "end_time": "09:30:00",
                "batch_code": "HDTN-1A-ZA1",
                "batch_name": "Super 30 - Batch A (2025)",
                "teacher_code": "AK-CAP",
                "teacher_name": "A K",
                "subject": "Physics",
                "is_locked": true
            }
        ]
    }
    """
    user = request.user
    
    # Check if user is Admin or Super Admin
    if user.role not in (AccountUser.ROLE_ADMIN, AccountUser.ROLE_SUPER_ADMIN):
        return Response(
            {"detail": "Only Admin and Super Admin can view fixed slots."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    # Get timetable
    try:
        timetable = Timetable.objects.select_related("center").get(id=timetable_id)
    except Timetable.DoesNotExist:
        return Response(
            {"detail": "Timetable not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions: Admin can only view their center's timetables
    if user.role == AccountUser.ROLE_ADMIN:
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if timetable.center != user.center:
            return Response(
                {"detail": "You can only view timetables in your center."},
                status=status.HTTP_403_FORBIDDEN,
            )
    
    # Get all fixed slots for this timetable
    fixed_slots = FixedSlot.objects.filter(
        timetable=timetable
    ).select_related("day_slot", "batch", "teacher").order_by("day_slot__day", "day_slot__slot_number", "batch__code")
    
    # Map day constant to display name
    day_display_map = {
        DaySlot.MONDAY: "Monday",
        DaySlot.TUESDAY: "Tuesday",
        DaySlot.WEDNESDAY: "Wednesday",
        DaySlot.THURSDAY: "Thursday",
        DaySlot.FRIDAY: "Friday",
        DaySlot.SATURDAY: "Saturday",
        DaySlot.SUNDAY: "Sunday",
    }
    
    fixed_slots_data = []
    for fixed_slot in fixed_slots:
        fixed_slots_data.append({
            "id": str(fixed_slot.id),
            "slot_code": fixed_slot.day_slot.slot_code,
            "day": day_display_map.get(fixed_slot.day_slot.day, fixed_slot.day_slot.day),
            "start_time": str(fixed_slot.day_slot.start_time),
            "end_time": str(fixed_slot.day_slot.end_time),
            "batch_code": fixed_slot.batch.code,
            "batch_name": fixed_slot.batch.name,
            "teacher_code": fixed_slot.teacher.teacher_code if fixed_slot.teacher else None,
            "teacher_name": f"{fixed_slot.teacher.first_name} {fixed_slot.teacher.last_name}".strip() if fixed_slot.teacher else None,
            "subject": fixed_slot.subject or "Free / Exam",
            "is_locked": fixed_slot.is_locked,
        })
    
    return Response(
        {
            "timetable_id": str(timetable.id),
            "timetable": str(timetable),
            "center": timetable.center.name,
            "from_date": str(timetable.from_date),
            "to_date": str(timetable.to_date),
            "fixed_slots": fixed_slots_data,
            "total": len(fixed_slots_data),
        },
        status=status.HTTP_200_OK,
    )

