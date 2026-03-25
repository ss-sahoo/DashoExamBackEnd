"""
Generic Algorithm for Timetable Optimization

This module contains:
1. Feasibility checking function
2. Random timetable generation algorithm
3. Helper functions to convert between Django models and algorithm data structures
"""

from collections import defaultdict
import numpy as np
import random
from typing import Dict, List, Optional, Tuple, Any


def check_timetable_feasibility_from_start(
    available_slots: Dict[str, Dict[str, str]],
    teachers: Dict[str, Any],
    batches: Dict[str, Any],
    new_fixed_slots: Dict[str, Dict[str, Dict[str, Optional[Tuple[str, str]]]]],
    start_slot: str
) -> Tuple[bool, Dict[str, List[str]]]:
    """
    Check if timetable generation is feasible from a given start slot.
    
    Returns:
        (feasible: bool, violations: dict)
    """
    
    def batch_classes_done_before_start(new_fixed_slots, slots_before_start):
        """Counts completed (non-None) classes per batch before start slot"""
        batch_done = defaultdict(int)
        
        for day, slots in new_fixed_slots.items():
            for slot, batch_map in slots.items():
                if slot not in slots_before_start:
                    continue
                
                for batch_code, entry in batch_map.items():
                    if entry is None:
                        continue  # IMPORTANT: ignore empty slots
                    batch_done[batch_code] += 1
        
        return batch_done
    
    def count_usable_slots_for_batch(batch_code, valid_slots_set, new_fixed_slots):
        """Counts slots that are usable for a batch (i.e. not fixed as None)"""
        blocked_slots = set()
        
        for day, slots in new_fixed_slots.items():
            for slot, batch_map in slots.items():
                if slot not in valid_slots_set:
                    continue
                
                # Slot explicitly blocked for this batch
                if batch_code in batch_map and batch_map[batch_code] is None:
                    blocked_slots.add(slot)
        
        return len(valid_slots_set - blocked_slots)
    
    def split_slots_by_start(available_slots, start_slot):
        """Split slots into before and after start_slot"""
        def flatten_slots(available_slots):
            ordered = []
            for day in available_slots:
                for slot in available_slots[day]:
                    ordered.append(slot)
            return ordered
        
        all_slots = flatten_slots(available_slots)
        if start_slot not in all_slots:
            raise ValueError(f"Invalid start slot {start_slot}")
        
        idx = all_slots.index(start_slot)
        return set(all_slots[:idx]), set(all_slots[idx:])
    
    def teacher_classes_done_before_start(new_fixed_slots, slots_before_start):
        """Count classes done by teachers before start slot"""
        teacher_done = defaultdict(int)
        
        for day, slots in new_fixed_slots.items():
            for slot, batch_map in slots.items():
                if slot not in slots_before_start:
                    continue
                
                for batch_code, entry in batch_map.items():
                    if entry is None:
                        continue
                    _, teacher_code = entry
                    teacher_done[teacher_code] += 1
        
        return teacher_done
    
    violations = defaultdict(list)
    
    # Split slots by start
    slots_before, valid_slots = split_slots_by_start(available_slots, start_slot)
    valid_slots_set = set(valid_slots)
    
    # Helper maps
    teacher_by_code = {t.code: t for t in teachers.values()}
    batch_by_code = {b.batch_code: b for b in batches.values()}
    
    # slot -> teachers available
    slot_teacher_map = defaultdict(set)
    for t in teachers.values():
        for s in t.avilable_slots:
            if s in valid_slots_set:
                slot_teacher_map[s].add(t.code)
    
    # RULE 1: Teachers available >= number of batches
    batch_count = len(batches)
    for slot in valid_slots:
        available_teachers = len(slot_teacher_map.get(slot, []))
        if available_teachers < batch_count:
            violations["RULE_1"].append(
                f"Slot {slot}: Available Teachers={available_teachers}, Total Batches={batch_count}"
            )
    
    # RULE 2: Fixed-slot teacher must be available
    for day, slots in new_fixed_slots.items():
        for slot, batch_map in slots.items():
            if slot not in valid_slots_set:
                continue
            
            for batch_code, entry in batch_map.items():
                if entry is None:
                    continue
                
                _, teacher_code = entry
                
                # Skip validation for slots without teacher (e.g., "Exam", "Free Period")
                if not teacher_code:
                    continue
                
                teacher = teacher_by_code.get(teacher_code)
                
                if not teacher:
                    violations["RULE_2"].append(
                        f"{day}-{slot}: Unknown teacher {teacher_code}"
                    )
                    continue
                
                if slot not in teacher.avilable_slots:
                    violations["RULE_2"].append(
                        f"{day}-{slot}: Teacher {teacher_code} not available"
                    )
    
    # RULE 3 and 4: Batch min/max classes constraints
    total_slots = len(valid_slots)
    done_before = batch_classes_done_before_start(new_fixed_slots, slots_before)
    
    for batch in batches.values():
        min_classes = sum(
            sub['min_class_per_week']
            for sub in batch.sub_teachers.values()
        )
        max_classes = sum(
            sub['max_class_per_week']
            for sub in batch.sub_teachers.values()
        )
        
        remaining_required = min_classes - done_before.get(batch.batch_code, 0)
        max_classes_remaining = max_classes - done_before.get(batch.batch_code, 0)
        
        usable_slots = count_usable_slots_for_batch(
            batch.batch_code,
            valid_slots_set,
            new_fixed_slots
        )
        
        if remaining_required > usable_slots:
            violations["RULE_3"].append(
                f"Batch {batch.batch_code}: "
                f"RemainingRequiredClasses={remaining_required}, "
                f"Total slots={total_slots}, Usable slots={usable_slots}"
            )
        
        if max_classes_remaining < usable_slots:
            violations["RULE_4"].append(
                f"Batch {batch.batch_code}: "
                f"MaxClasses={max_classes_remaining}, "
                f"Total slots={total_slots}, Usable slots={usable_slots}"
            )
        
        # RULE 5: maximum must be sufficient
        if max_classes_remaining < remaining_required:
            violations["RULE_5"].append(
                f"Batch {batch.batch_code}: "
                f"RemainingMax={max_classes_remaining}, RemainingMin={remaining_required}"
            )
    
    # RULE 6: Teacher min load <= teacher availability
    teacher_min_load = defaultdict(int)
    for batch in batches.values():
        for sub in batch.sub_teachers.values():
            teacher_min_load[sub['teacher'].code] += sub['min_class_per_week']
    
    done_before_teachers = teacher_classes_done_before_start(new_fixed_slots, slots_before)
    
    for teacher_code, min_load in teacher_min_load.items():
        teacher = teacher_by_code[teacher_code]
        available_after = len(
            [s for s in teacher.avilable_slots if s in valid_slots_set]
        )
        
        remaining_required = min_load - done_before_teachers.get(teacher_code, 0)
        
        if remaining_required > available_after:
            violations["RULE_6"].append(
                f"Teacher {teacher_code}: "
                f"RemainingMin={remaining_required}, "
                f"AvailableAfterStart={available_after}, "
                f"DoneBefore={done_before_teachers.get(teacher_code, 0)}"
            )
    
    # Result
    # RULE_4 is a warning (max classes < slots), not a blocker
    # Only RULE_1, RULE_2, RULE_5 are hard failures
    feasible = (
        len(violations['RULE_1']) + 
        len(violations['RULE_2']) + 
        len(violations['RULE_5']) == 0
    )
    
    return feasible, dict(violations)


def get_day_from_slot(slot_code: str) -> str:
    """
    Extract day key from slot code.
    
    Examples:
        'm1' -> 'mon' (m = monday)
        'tu3' -> 'tue' (tu = tuesday)
        'w2' -> 'wed' (w = wednesday)
        'th4' -> 'thu' (th = thursday)
        'f1' -> 'fri' (f = friday)
        'sa2' -> 'sat' (sa = saturday)
        'su1' -> 'sun' (su = sunday)
        'd1_1' -> 'd1' (date-based)
    """
    slot_lower = slot_code.lower()
    
    # Date-based slots (d1, d2, d1_1, d2_3, etc.)
    if slot_lower.startswith('d') and len(slot_lower) > 1:
        # Extract d1, d2, etc. from d1_1, d2_3, etc.
        if '_' in slot_lower:
            return slot_lower.split('_')[0]
        # Extract d1, d2 from d11, d23 (day + slot number)
        for i, char in enumerate(slot_lower[1:], 1):
            if not char.isdigit():
                break
        else:
            # All digits after 'd', find where day ends
            # Assume single digit day index for simplicity
            return slot_lower[:2] if len(slot_lower) > 2 else slot_lower
        return slot_lower[:i]
    
    # Weekly slots
    prefix_map = {
        'm': 'mon',
        'tu': 'tue',
        'w': 'wed',
        'th': 'thu',
        'f': 'fri',
        'sa': 'sat',
        'su': 'sun',
    }
    
    # Check two-character prefixes first
    if len(slot_lower) >= 2:
        two_char = slot_lower[:2]
        if two_char in prefix_map:
            return prefix_map[two_char]
    
    # Check single-character prefixes
    if slot_lower[0] in prefix_map:
        return prefix_map[slot_lower[0]]
    
    # Fallback: return the slot code itself
    return slot_code


def generate_new_fixed_slots(
    timetable: Dict[str, Dict[str, Dict[str, Tuple[str, str]]]],
    original_fixed_slots: Dict[str, Dict[str, Dict[str, Optional[Tuple[str, str]]]]],
    available_slots: Dict[str, Dict[str, str]],
    stop_slot: str
) -> Dict[str, Dict[str, Dict[str, Optional[Tuple[str, str]]]]]:
    """
    Generate new fixed slots by taking values from the generated timetable
    up to (and including) the stop_slot, then merging with original fixed slots.
    
    This allows regenerating the timetable from a specific point while keeping
    the assignments before that point fixed.
    
    Args:
        timetable: The generated timetable {day: {slot: {batch: (subject, teacher)}}}
        original_fixed_slots: Original fixed slots from admin
        available_slots: Available slots structure {day: {slot: time_range}}
        stop_slot: The slot code to stop at (e.g., 'w3', 'm2', 'd1_3')
    
    Returns:
        New fixed slots dict that includes timetable values up to stop_slot
    """
    stop_day = get_day_from_slot(stop_slot)
    new_fixed = defaultdict(lambda: defaultdict(dict))
    stop_reached = False
    
    # Iterate through available_slots in order
    for day in available_slots:
        if stop_reached:
            break
            
        for slot in available_slots[day]:
            if stop_reached:
                break
            
            # Take timetable values for this slot
            if day in timetable and slot in timetable[day]:
                for cls, value in timetable[day][slot].items():
                    new_fixed[day][slot][cls] = value
            
            # Check stop condition
            if day == stop_day and slot == stop_slot:
                stop_reached = True
    
    # Merge original fixed slots (they take precedence for None values)
    for day, slots in original_fixed_slots.items():
        for slot, classes in slots.items():
            for cls, value in classes.items():
                if cls in new_fixed[day][slot]:
                    # If new_fixed has None, use original value
                    if new_fixed[day][slot][cls] is None:
                        new_fixed[day][slot][cls] = value
                else:
                    # Add original fixed slot
                    new_fixed[day][slot][cls] = value
    
    # Convert defaultdict to regular dict
    return {day: dict(slots) for day, slots in new_fixed.items()}


def generate_random_timetable(
    batches: Dict[str, Any],
    teachers: Dict[str, Any],
    avilable_slots: Dict[str, Dict[str, str]],
    fixed_slots: Optional[Dict[str, Dict[str, Dict[str, Optional[Tuple[str, str]]]]]] = None,
    MAX_RETRIES: int = 1000,
    max_try_for_slot_assign: int = 100,
    weight_power_fector: int = 3,
    max_one_subject_repetation_per_day: int = 2,
    max_one_subject_repetation_per_day_penalty_fector: float = 0,
    weight_penalty_consu_sub_repetation: List[float] = [0.01, 0, 0, 0, 0]
) -> Dict[str, Dict[str, Dict[str, Tuple[str, str]]]]:
    """
    Generate a random timetable using the genetic algorithm approach.
    
    Returns:
        timetable dict: {day: {slot: {batch_code: (subject, teacher_code)}}}
    """
    
    for attempt in range(MAX_RETRIES):
        try:
            timetable = defaultdict(lambda: defaultdict(dict))
            batch_teacher_count = defaultdict(lambda: defaultdict(int))
            batch_subject_count = defaultdict(lambda: defaultdict(int))
            teacher_busy = defaultdict(set)  # Reset per day
            
            for day, slots in avilable_slots.items():
                batch_day_teacher_count = defaultdict(lambda: defaultdict(int))
                batch_day_subject_count = defaultdict(lambda: defaultdict(int))
                slot_ids = list(slots.keys())
                
                for slot in slot_ids:
                    # Fixed slot assignments
                    if fixed_slots and day in fixed_slots and slot in fixed_slots[day]:
                        for fixed_batch_code, fixed_value in fixed_slots[day][slot].items():
                            if fixed_value is None:
                                continue  # Blocked slot - skip this batch for this slot
                            
                            subject, teacher_code = fixed_value
                            
                            # Handle slots without teacher (e.g., "Exam", "Free Period")
                            if not teacher_code:
                                # Just mark the slot as occupied for this batch, no teacher needed
                                timetable[day][slot][fixed_batch_code] = (subject, "")
                                batch_subject_count[fixed_batch_code][subject] += 1
                                batch_day_subject_count[fixed_batch_code][subject] += 1
                                continue
                            
                            # Normal fixed slot with teacher
                            teacher_obj = next((t for t in teachers.values() if t.code == teacher_code), None)
                            if not teacher_obj:
                                raise Exception(f"Teacher {teacher_code} not found.")
                            
                            if slot not in teacher_obj.avilable_slots:
                                raise Exception(f"Teacher {teacher_code} not available at {slot} for fixed slot on {day}.")
                            if teacher_code in teacher_busy[slot]:
                                raise Exception(f"Teacher {teacher_code} already assigned in slot {slot} on {day}.")
                            
                            timetable[day][slot][fixed_batch_code] = (subject, teacher_code)
                            batch_teacher_count[fixed_batch_code][teacher_code] += 1
                            batch_subject_count[fixed_batch_code][subject] += 1
                            batch_day_teacher_count[fixed_batch_code][teacher_code] += 1
                            batch_day_subject_count[fixed_batch_code][subject] += 1
                            teacher_busy[slot].add(teacher_code)
                    
                    batch_keys = list(batches.keys())
                    max_try = max_try_for_slot_assign
                    tried = 0
                    
                    while True:
                        random.shuffle(batch_keys)
                        no_of_batches = len(batch_keys)
                        temp_assignments = {}
                        temp_teacher_busy = set(teacher_busy[slot])
                        i = 0
                        done = False
                        
                        while i < no_of_batches:
                            batch_key = batch_keys[i]
                            i += 1
                            batch = batches[batch_key]
                            
                            if fixed_slots and day in fixed_slots and slot in fixed_slots[day] and batch.batch_code in fixed_slots[day][slot]:
                                if i == no_of_batches:
                                    done = True
                                continue
                            
                            # Get previous slot subjects/teachers for this day
                            slot_index = list(avilable_slots[day].keys()).index(slot)
                            prev_subjects_list = []
                            prev_teachers_list = []
                            for index in range(slot_index):
                                sl = list(avilable_slots[day].keys())[index]
                                entry = timetable.get(day, {}).get(sl, {}).get(batch.batch_code)
                                if entry:
                                    prev_subjects_list.append(entry[0])
                                    prev_teachers_list.append(entry[1])
                            prev_subjects_list.reverse()
                            prev_teachers_list.reverse()
                            
                            sub_list = list(batch.sub_teachers.keys())
                            subject_weights = []
                            sub_list_with_weight = []
                            
                            for sub in sub_list:
                                min_class = batch.sub_teachers[sub]['min_class_per_week']
                                max_class = batch.sub_teachers[sub]['max_class_per_week']
                                subject = batch.sub_teachers[sub]['subject']
                                teacher_code = batch.sub_teachers[sub]['teacher'].code
                                current_count = batch_teacher_count[batch.batch_code][teacher_code]
                                current_day_sub_count = batch_day_subject_count[batch.batch_code][subject]
                                
                                weight = (min_class - current_count + 1) if current_count < min_class else 1
                                weight = weight ** weight_power_fector
                                
                                # Penalize if same as previous slot's subject
                                subject_consu_repetation_count = 0
                                for pre_subject in prev_subjects_list:
                                    if subject == pre_subject:
                                        subject_consu_repetation_count += 1
                                    else:
                                        break
                                
                                if subject_consu_repetation_count > 0:
                                    if subject_consu_repetation_count < 6:
                                        weight *= weight_penalty_consu_sub_repetation[subject_consu_repetation_count - 1]
                                    else:
                                        weight = 0
                                
                                # Penalize if same subject taught more than max per day
                                if current_day_sub_count > max_one_subject_repetation_per_day - 1:
                                    weight = weight * max_one_subject_repetation_per_day_penalty_fector
                                
                                if weight > 0:
                                    sub_list_with_weight.append(sub)
                                    subject_weights.append(weight)
                            
                            if not sub_list_with_weight:
                                raise Exception(f"No valid subjects for batch {batch.batch_code} at {day} {slot}")
                            
                            subject_probs = np.array(subject_weights, dtype=np.float64)
                            subject_probs /= subject_probs.sum()
                            sub_list_with_weight = list(np.random.choice(
                                sub_list_with_weight, 
                                size=len(sub_list_with_weight), 
                                replace=False, 
                                p=subject_probs
                            ))
                            
                            assigned = False
                            for sub in sub_list_with_weight:
                                teacher_obj = batch.sub_teachers[sub]['teacher']
                                teacher_code = teacher_obj.code
                                max_class = batch.sub_teachers[sub]['max_class_per_week']
                                max_class_day = batch.sub_teachers[sub]['max_class_per_day']
                                subject = batch.sub_teachers[sub]['subject']
                                
                                if (
                                    slot in teacher_obj.avilable_slots and
                                    teacher_obj.code not in temp_teacher_busy and
                                    batch_teacher_count[batch.batch_code][teacher_code] < max_class and
                                    batch_day_teacher_count[batch.batch_code][teacher_code] < max_class_day
                                ):
                                    temp_assignments[batch.batch_code] = (subject, teacher_obj.code)
                                    temp_teacher_busy.add(teacher_obj.code)
                                    assigned = True
                                    break
                            
                            if i == no_of_batches and assigned:
                                done = True
                            if not assigned:
                                tried += 1
                                if tried > max_try:
                                    raise Exception(f"Cannot assign for batch {batch.batch_code} at {day} {slot}. Need more teachers or class capacity.")
                                break
                        
                        if done:
                            # Commit assignments
                            for batch_code, (subject, teacher_code) in temp_assignments.items():
                                timetable[day][slot][batch_code] = (subject, teacher_code)
                                batch_teacher_count[batch_code][teacher_code] += 1
                                batch_subject_count[batch_code][subject] += 1
                                batch_day_teacher_count[batch_code][teacher_code] += 1
                                batch_day_subject_count[batch_code][subject] += 1
                                teacher_busy[slot].add(teacher_code)
                            break
            
            return dict(timetable)  # Success, return timetable
            
        except Exception as e:
            if ((attempt + 1) % 100) == 0:
                print(f"[Global Retry {attempt + 1}/{MAX_RETRIES}] Failed to generate timetable: {e}")
            continue  # Try whole generation again from scratch
    
    # If all retries failed
    raise Exception(f"Failed to generate valid timetable after {MAX_RETRIES} retries.")


# =============================================================================
# GENETIC ALGORITHM FUNCTIONS
# =============================================================================

import copy


def fitness_score(
    timetable: Dict[str, Dict[str, Dict[str, Tuple[str, str]]]],
    batches: Dict[str, Any],
    teachers: Dict[str, Any],
    avilable_slots: Dict[str, Dict[str, str]],
    fixed_slots: Optional[Dict[str, Dict[str, Dict[str, Optional[Tuple[str, str]]]]]] = None,
    hard_constraint_penalty: int = 30000,
    min_weekly_classes_penalty: int = 40,
    min_weekly_classes_penalty_exponent: int = 2,
    max_weekly_classes_penalty: int = 200,
    max_weekly_classes_penalty_exponent: int = 4,
    consu_sub_rep_penalty: int = 40,
    consu_sub_rep_penalty_fector: int = 3,
    sub_variation_per_day_reward_fector: float = 1.2,
    sub_spread_over_week_reward_fector: float = 2.0
) -> float:
    """
    Calculate fitness score for a timetable.
    Higher score = better timetable.
    
    Constraints checked:
    1. Teacher unavailable in slot (hard)
    2. Teacher double booking (hard)
    3. Min/Max weekly classes per teacher
    4. No back-to-back same subject
    5. Subject repetition per day (max 2-3 times)
    6. Subject variety per day (reward)
    7. Subject spread over week (reward)
    8. Fixed slot violations (hard)
    """
    penalty = 0
    reward = 0
    
    teacher_slot_map = defaultdict(set)
    batch_teacher_counter = defaultdict(lambda: defaultdict(int))
    teacher_availability = {t.code: set(t.avilable_slots) for t in teachers.values()}
    subject_days = defaultdict(lambda: defaultdict(set))
    max_min_class = {}
    
    # Process timetable
    for day, slots in timetable.items():
        for slot, batch_data in slots.items():
            for batch_code, entry in batch_data.items():
                if not entry or len(entry) < 2:
                    continue
                subject, teacher_code = entry
                
                # Skip entries without teacher (Exam, Free Period)
                if not teacher_code:
                    continue
                
                # Constraint 1: Teacher unavailable in that slot
                if teacher_code in teacher_availability:
                    if slot not in teacher_availability[teacher_code]:
                        penalty += hard_constraint_penalty
                
                # Constraint 2: Double booking
                if teacher_code in teacher_slot_map[slot]:
                    penalty += hard_constraint_penalty
                else:
                    teacher_slot_map[slot].add(teacher_code)
                
                # Track count and day for subjects
                batch_teacher_counter[batch_code][teacher_code] += 1
                subject_days[batch_code][subject].add(day)
    
    # Calculate max min_class for each batch
    for batch_key, batch in batches.items():
        maximum_min_class = 0
        for subject, teacher_data in batch.sub_teachers.items():
            min_class = teacher_data['min_class_per_week']
            if maximum_min_class < min_class:
                maximum_min_class = min_class
        max_min_class[batch.batch_code] = maximum_min_class
    
    # Constraint 3: Min/Max weekly class check
    for batch_key, batch in batches.items():
        for subject, teacher_data in batch.sub_teachers.items():
            teacher_code = teacher_data['teacher'].code
            count = batch_teacher_counter[batch.batch_code].get(teacher_code, 0)
            min_class = teacher_data['min_class_per_week']
            max_class = teacher_data['max_class_per_week']
            maximum_min_class = max_min_class.get(batch.batch_code, 1)
            
            if count < min_class:
                ratio = maximum_min_class / min_class if min_class > 0 else 1
                penalty += (ratio * (min_class - count)) ** min_weekly_classes_penalty_exponent * min_weekly_classes_penalty
            elif count > max_class:
                penalty += (count - max_class) ** max_weekly_classes_penalty_exponent * max_weekly_classes_penalty
    
    # Constraint 4: No back-to-back same subject
    for day in avilable_slots:
        slot_ids = list(avilable_slots[day].keys())
        for batch_key in batches:
            prev_subject = None
            subject_repetation_count = 0
            
            for slot_id in slot_ids:
                entry = timetable.get(day, {}).get(slot_id, {}).get(batches[batch_key].batch_code)
                subject = entry[0] if entry and len(entry) >= 1 else None
                
                if subject is not None and prev_subject == subject:
                    subject_repetation_count += 1
                else:
                    if subject_repetation_count > 0:
                        penalty += (subject_repetation_count ** consu_sub_rep_penalty_fector) * consu_sub_rep_penalty
                    subject_repetation_count = 0
                prev_subject = subject
            
            if subject_repetation_count > 0:
                penalty += (subject_repetation_count ** consu_sub_rep_penalty_fector) * consu_sub_rep_penalty
    
    # Constraint 5: Subject repetition per day (max 2-3 times)
    for batch_key, batch in batches.items():
        for day in avilable_slots:
            subject_daily_counter = defaultdict(int)
            for slot in avilable_slots[day]:
                entry = timetable.get(day, {}).get(slot, {}).get(batch.batch_code)
                if entry and len(entry) >= 1:
                    subject = entry[0]
                    subject_daily_counter[subject] += 1
            
            for subject, count in subject_daily_counter.items():
                if count > 2:
                    penalty += 100
    
    # Constraint 6: Subject variety per day (reward)
    for day in avilable_slots:
        for batch_key in batches:
            subjects_today = []
            for slot_id in avilable_slots[day]:
                entry = timetable.get(day, {}).get(slot_id, {}).get(batches[batch_key].batch_code)
                if entry and len(entry) >= 1:
                    subjects_today.append(entry[0])
            
            if subjects_today:
                subject_set = set(subjects_today)
                reward += len(subject_set) ** sub_variation_per_day_reward_fector
    
    # Constraint 7: Same subject spread over week (reward)
    for batch_code in subject_days:
        for subject in subject_days[batch_code]:
            days_appeared = len(subject_days[batch_code][subject])
            reward += days_appeared ** sub_spread_over_week_reward_fector
    
    # Constraint 8: Fixed slot violation
    if fixed_slots:
        batch_code_to_key = {batch.batch_code: key for key, batch in batches.items()}
        for day in fixed_slots:
            for slot in fixed_slots[day]:
                for batch_code, expected_value in fixed_slots[day][slot].items():
                    if expected_value is None:
                        # Check if slot should be empty
                        actual = timetable.get(day, {}).get(slot, {}).get(batch_code)
                        if actual is not None:
                            penalty += hard_constraint_penalty
                        continue
                    
                    expected_subject, expected_teacher_code = expected_value
                    key = batch_code_to_key.get(batch_code)
                    if not key:
                        penalty += 100
                        continue
                    
                    entry = timetable.get(day, {}).get(slot, {}).get(batches[key].batch_code)
                    if not entry:
                        penalty += 100
                    else:
                        assigned_subject, assigned_teacher = entry
                        if assigned_subject != expected_subject:
                            penalty += hard_constraint_penalty
                        if expected_teacher_code and assigned_teacher != expected_teacher_code:
                            penalty += hard_constraint_penalty
    
    return reward - penalty


def crossover(
    t1: Dict[str, Dict[str, Dict[str, Tuple[str, str]]]],
    t2: Dict[str, Dict[str, Dict[str, Tuple[str, str]]]],
    fixed_slots: Optional[Dict] = None
) -> Dict[str, Dict[str, Dict[str, Tuple[str, str]]]]:
    """
    Crossover two timetables to create a child.
    Randomly selects days from each parent.
    """
    days = list(t1.keys())
    child = copy.deepcopy(t1)
    
    # Take half the days from t2
    for day in random.sample(days, len(days) // 2):
        child[day] = copy.deepcopy(t2[day])
    
    return child


def mutate(
    timetable: Dict[str, Dict[str, Dict[str, Tuple[str, str]]]],
    batches: Dict[str, Any],
    teachers: Dict[str, Any],
    mutation_rate: float = 0.02
) -> None:
    """
    Mutate a timetable by randomly changing some assignments.
    Modifies timetable in place.
    """
    for day in timetable:
        for slot in list(timetable[day].keys()):
            if random.random() < mutation_rate:
                batch_codes = list(timetable[day][slot].keys())
                if not batch_codes:
                    continue
                
                # Choose one batch randomly
                batch_code = random.choice(batch_codes)
                entry = timetable[day][slot].get(batch_code)
                if not entry or len(entry) < 2:
                    continue
                
                subject, old_teacher_code = entry
                
                # Skip entries without teacher (Exam, Free Period)
                if not old_teacher_code:
                    continue
                
                # Get the actual Batch object
                batch_obj = None
                for b in batches.values():
                    if b.batch_code == batch_code:
                        batch_obj = b
                        break
                
                if not batch_obj:
                    continue
                
                # Get list of all teacher codes already teaching in this slot
                busy_teachers = set()
                for _, tc in timetable[day][slot].values():
                    if tc:
                        busy_teachers.add(tc)
                
                # Try to reassign with a different subject & valid teacher
                possible_subjects = list(batch_obj.sub_teachers.keys())
                random.shuffle(possible_subjects)
                
                for new_sub in possible_subjects:
                    new_teacher = batch_obj.sub_teachers[new_sub]['teacher']
                    new_teacher_code = new_teacher.code
                    
                    if (slot in new_teacher.avilable_slots and
                        new_teacher_code not in busy_teachers and
                        new_teacher_code != old_teacher_code):
                        timetable[day][slot][batch_code] = (batch_obj.sub_teachers[new_sub]['subject'], new_teacher_code)
                        break


def run_genetic_algorithm(
    batches: Dict[str, Any],
    teachers: Dict[str, Any],
    avilable_slots: Dict[str, Dict[str, str]],
    fixed_slots: Optional[Dict[str, Dict[str, Dict[str, Optional[Tuple[str, str]]]]]] = None,
    generations: int = 100,
    population_size: int = 50,
    mutation_rate: float = 0.03,
    elite_size: int = 10,
    tournament_size: int = 5,
    max_retries_per_individual: int = 100,
    progress_callback: Optional[callable] = None
) -> Tuple[Dict[str, Dict[str, Dict[str, Tuple[str, str]]]], float]:
    """
    Run the genetic algorithm to optimize timetable.
    
    Args:
        batches: Batch configuration
        teachers: Teacher configuration
        avilable_slots: Available slots
        fixed_slots: Fixed slot constraints
        generations: Number of generations to run
        population_size: Size of population
        mutation_rate: Probability of mutation
        elite_size: Number of elite individuals to keep
        tournament_size: Tournament selection size
        max_retries_per_individual: Max retries when generating initial population
        progress_callback: Optional callback(generation, best_fitness) for progress updates
    
    Returns:
        (best_timetable, best_fitness)
    """
    # Generate initial population
    population = []
    for i in range(population_size):
        try:
            timetable = generate_random_timetable(
                batches, teachers, avilable_slots, fixed_slots,
                MAX_RETRIES=max_retries_per_individual
            )
            fitness = fitness_score(timetable, batches, teachers, avilable_slots, fixed_slots)
            population.append((timetable, fitness))
        except Exception as e:
            # If we can't generate enough individuals, continue with what we have
            if len(population) >= elite_size:
                break
            continue
    
    if not population:
        raise Exception("Failed to generate any valid timetables for initial population")
    
    # Run genetic algorithm
    for gen in range(generations):
        # Sort by fitness (descending)
        population.sort(key=lambda x: x[1], reverse=True)
        
        # Keep elite individuals
        new_population = population[:elite_size]
        
        # Generate new individuals
        while len(new_population) < population_size:
            # Tournament selection
            parent1 = random.choice(population[:tournament_size])[0]
            parent2 = random.choice(population[:tournament_size])[0]
            
            # Crossover
            child = crossover(parent1, parent2, fixed_slots)
            
            # Mutation
            mutate(child, batches, teachers, mutation_rate)
            
            # Calculate fitness
            score = fitness_score(child, batches, teachers, avilable_slots, fixed_slots)
            new_population.append((child, score))
        
        population = new_population
        
        # Progress callback
        if progress_callback:
            progress_callback(gen + 1, population[0][1])
        
        # Log progress every 10 generations
        if (gen + 1) % 10 == 0:
            print(f"Generation {gen + 1}: Best Fitness = {population[0][1]}")
    
    # Return best timetable
    population.sort(key=lambda x: x[1], reverse=True)
    best_timetable, best_fitness = population[0]
    
    return best_timetable, best_fitness


def check_constraints(
    timetable: Dict[str, Dict[str, Dict[str, Tuple[str, str]]]],
    batches: Dict[str, Any],
    teachers: Dict[str, Any],
    avilable_slots: Dict[str, Dict[str, str]],
    fixed_slots: Optional[Dict] = None
) -> Dict[str, List[str]]:
    """
    Check all constraints and return violations.
    """
    violations = defaultdict(list)
    
    teacher_slot_map = defaultdict(set)
    batch_teacher_counter = defaultdict(lambda: defaultdict(int))
    teacher_availability = {t.code: set(t.avilable_slots) for t in teachers.values()}
    
    # Check basic constraints
    for day, slots in timetable.items():
        for slot, batch_data in slots.items():
            for batch_code, entry in batch_data.items():
                if not entry or len(entry) < 2:
                    continue
                subject, teacher_code = entry
                
                if not teacher_code:
                    continue
                
                # Teacher unavailable
                if teacher_code in teacher_availability:
                    if slot not in teacher_availability[teacher_code]:
                        violations["teacher_unavailable"].append(
                            f"{day}-{slot}: {teacher_code} not available"
                        )
                
                # Double booking
                if teacher_code in teacher_slot_map[slot]:
                    violations["double_booking"].append(
                        f"{day}-{slot}: {teacher_code} double booked"
                    )
                else:
                    teacher_slot_map[slot].add(teacher_code)
                
                batch_teacher_counter[batch_code][teacher_code] += 1
    
    # Min/Max class violations
    for batch_key, batch in batches.items():
        for subject, teacher_data in batch.sub_teachers.items():
            teacher_code = teacher_data['teacher'].code
            count = batch_teacher_counter[batch.batch_code].get(teacher_code, 0)
            min_class = teacher_data['min_class_per_week']
            max_class = teacher_data['max_class_per_week']
            
            if count < min_class:
                violations["min_class"].append(
                    f"{batch.batch_code}-{teacher_code}: {count}/{min_class} classes"
                )
            if count > max_class:
                violations["max_class"].append(
                    f"{batch.batch_code}-{teacher_code}: {count}/{max_class} classes"
                )
    
    return dict(violations)

