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
    feasible = (
        len(violations['RULE_1']) + 
        len(violations['RULE_2']) + 
        len(violations['RULE_4']) + 
        len(violations['RULE_5']) == 0
    )
    
    return feasible, dict(violations)


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
                                continue  # Free slot
                            
                            subject, teacher_code = fixed_value
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

