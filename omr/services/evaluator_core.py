#!/usr/bin/env python3
"""
OMR Sheet Evaluator
Uses scanned images and layout metadata to evaluate responses and produce exam results
"""

import json
import cv2
import numpy as np
import os
from typing import List, Dict, Tuple
from dataclasses import dataclass
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.colors import green, red, black

# Import global variables from generator_core (local module)
from .generator_core import BUBBLE_RADIUS, BUBBLE_VERTICAL_SPACING

try:
    from pdf2image import convert_from_path
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False


# BUBBLE DETECTION CONFIGURATION

FILL_THRESHOLD = 0.39
BUBBLE_SEARCH_RADIUS_MM = BUBBLE_RADIUS / mm * 0.99


@dataclass
class EvaluatedBubble:
    """Bubble detection result"""
    field_name: str
    value: str
    is_filled: bool
    fill_ratio: float


# PDF TO IMAGE CONVERSION

def convert_pdf_to_images(pdf_path: str) -> List[str]:
    """
    Convert PDF pages to temporary image files.
    Returns list of temporary image file paths.
    """
    if not PDF_SUPPORT:
        raise ImportError("pdf2image library not installed. Install with: pip install pdf2image")

    # Convert PDF to images (one per page)
    images = convert_from_path(pdf_path, dpi=300)

    # Save as temporary image files
    temp_image_paths = []
    base_name = os.path.splitext(pdf_path)[0]

    for i, image in enumerate(images, start=1):
        temp_path = f"{base_name}_page{i}_temp.png"
        image.save(temp_path, 'PNG')
        temp_image_paths.append(temp_path)

    return temp_image_paths


# IMAGE PREPROCESSING

def detect_alignment_boxes(gray_image: np.ndarray) -> Tuple[np.ndarray, bool]:
    """
    Detect the four corner alignment boxes in the image and extract their outer corner points.

    Uses cv2.minAreaRect() to get the actual rotated rectangle corners, which is more
    accurate than axis-aligned bounding boxes, especially for rotated/skewed scans.

    Extracts the appropriate corner from each rotated box:
    - Top-left box → use its top-left corner
    - Top-right box → use its top-right corner
    - Bottom-left box → use its bottom-left corner
    - Bottom-right box → use its bottom-right corner

    Returns: (corners_array, success) where corners_array is [[x, y], ...] for TL, TR, BL, BR
    """
    # Apply thresholding to detect black squares
    _, binary = cv2.threshold(gray_image, 127, 255, cv2.THRESH_BINARY_INV)

    # Find contours
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Filter for square-like contours (alignment boxes)
    box_candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 100:  # Too small
            continue

        # Use minAreaRect to get rotated rectangle (better for rotated boxes)
        rect = cv2.minAreaRect(contour)
        (center_x, center_y), (width, height), angle = rect

        # Check if it's roughly square (aspect ratio close to 1)
        aspect_ratio = max(width, height) / (min(width, height) + 1e-6)
        if aspect_ratio < 1.5:  # Square-ish
            # Get the 4 corner points of the rotated rectangle
            box_points = cv2.boxPoints(rect)  # Returns 4 corners as [(x,y), ...]

            # Calculate center for quadrant identification
            cx = int(center_x)
            cy = int(center_y)

            # Store: (center_x, center_y, area, rotated_box_corners)
            box_candidates.append((cx, cy, area, box_points))

    if len(box_candidates) < 4:
        print(f"[WARNING] Found only {len(box_candidates)} alignment boxes, expected 4")
        return None, False

    # Sort by area and take the 4 largest (should be our alignment boxes)
    box_candidates.sort(key=lambda x: x[2], reverse=True)
    boxes = box_candidates[:4]

    # Sort boxes into corners based on their centers: TL, TR, BL, BR
    # Top boxes have smaller y, bottom boxes have larger y
    boxes.sort(key=lambda p: p[1])  # Sort by center y
    top_boxes = sorted(boxes[:2], key=lambda p: p[0])  # Top 2, sorted by center x
    bottom_boxes = sorted(boxes[2:], key=lambda p: p[0])  # Bottom 2, sorted by center x

    def get_corner_point(box_data, position):
        """
        Extract the appropriate corner from the rotated rectangle's 4 corners.

        box_points from cv2.boxPoints are ordered, but we need to identify which
        point corresponds to which corner of the box, then select the appropriate one.
        """
        cx, cy, area, box_points = box_data

        # Sort points: first by y (top to bottom), then by x (left to right)
        # This gives us: [TL, TR, BL, BR] or similar ordering
        points = sorted(box_points, key=lambda p: (p[1], p[0]))

        # Split into top 2 and bottom 2
        top_2 = sorted(points[:2], key=lambda p: p[0])  # Left to right
        bottom_2 = sorted(points[2:], key=lambda p: p[0])  # Left to right

        # Now we have: top_2 = [TL, TR], bottom_2 = [BL, BR]
        if position == 'TL':  # Top-left box → use top-left corner
            return tuple(top_2[0])
        elif position == 'TR':  # Top-right box → use top-right corner
            return tuple(top_2[1])
        elif position == 'BL':  # Bottom-left box → use bottom-left corner
            return tuple(bottom_2[0])
        elif position == 'BR':  # Bottom-right box → use bottom-right corner
            return tuple(bottom_2[1])

    corners = np.array([
        get_corner_point(top_boxes[0], 'TL'),      # Top-left
        get_corner_point(top_boxes[1], 'TR'),      # Top-right
        get_corner_point(bottom_boxes[0], 'BL'),   # Bottom-left
        get_corner_point(bottom_boxes[1], 'BR')    # Bottom-right
    ], dtype=np.float32)

    return corners, True


def crop_and_align_to_a4(image: np.ndarray, debug_image_path: str = None) -> Tuple[np.ndarray, float]:
    """
    Detect alignment boxes, crop and perspective-correct the image to exact A4 dimensions.

    This function handles:
    1. Skewed/rotated scans - The perspective transform automatically corrects rotation
    2. Non-uniform scaling - Normalizes to exact A4 dimensions
    3. Coordinate alignment - After transformation, the image coordinates match metadata coordinates

    The key insight: The metadata coordinates are in the "ideal" A4 space (210mm x 297mm),
    and this transformation brings the scanned image into that same coordinate space.
    Therefore, bubble coordinates from metadata work directly on the aligned image!

    Returns: (aligned_image, pixels_per_mm)
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Detect the four corner alignment boxes
    corners, success = detect_alignment_boxes(gray)

    if not success or corners is None:
        print("[WARNING] Alignment box detection failed, using full image")
        # Fallback: use original image and estimate scale
        a4_height_mm = 297
        img_height_px = image.shape[0]
        pixels_per_mm = img_height_px / a4_height_mm
        return image, pixels_per_mm, None

    # A4 dimensions in mm (from generator.py PAGE_WIDTH and PAGE_HEIGHT)
    a4_width_mm = 210
    a4_height_mm = 297

    # Target resolution: use a standard DPI (e.g., 300 DPI)
    # 300 DPI = 300 pixels per inch = 300/25.4 pixels per mm ≈ 11.81 pixels/mm
    target_pixels_per_mm = 300 / 25.4

    # Calculate target dimensions in pixels
    target_width_px = int(a4_width_mm * target_pixels_per_mm)
    target_height_px = int(a4_height_mm * target_pixels_per_mm)

    # Define destination points for perspective transform (A4 rectangle)
    # These correspond to the alignment box positions in the ideal A4 coordinate system
    dst_corners = np.array([
        [0, 0],                                    # Top-left
        [target_width_px - 1, 0],                  # Top-right
        [0, target_height_px - 1],                 # Bottom-left
        [target_width_px - 1, target_height_px - 1] # Bottom-right
    ], dtype=np.float32)

    # Compute perspective transformation matrix
    # This matrix maps from skewed/rotated image coordinates to ideal A4 coordinates
    matrix = cv2.getPerspectiveTransform(corners, dst_corners)

    # Apply perspective transformation
    # This corrects for: rotation, skew, non-uniform scaling, perspective distortion
    aligned = cv2.warpPerspective(image, matrix, (target_width_px, target_height_px))

    # Calculate rotation angle for logging
    dx = corners[1][0] - corners[0][0]  # Top-right X - Top-left X
    dy = corners[1][1] - corners[0][1]  # Top-right Y - Top-left Y
    rotation_angle = np.degrees(np.arctan2(dy, dx))

    print(f"[ALIGNMENT] Detected corners: {corners.astype(int).tolist()}")
    print(f"[ALIGNMENT] Rotation angle: {rotation_angle:.2f}°")
    print(f"[ALIGNMENT] Output size: {target_width_px}x{target_height_px} pixels ({a4_width_mm}x{a4_height_mm} mm)")
    print(f"[ALIGNMENT] Pixels per mm: {target_pixels_per_mm:.2f}")

    # Save debug image if path provided
    if debug_image_path:
        debug_img = image.copy()
        # Draw detected corners on original image
        for i, (x, y) in enumerate(corners.astype(int)):
            cv2.circle(debug_img, (x, y), 20, (0, 255, 0), 5)
            cv2.putText(debug_img, f"C{i}", (x+30, y+30), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 255, 0), 3)
        cv2.imwrite(debug_image_path.replace('.png', '_corners.png'), debug_img)
        cv2.imwrite(debug_image_path, aligned)
        print(f"[DEBUG] Saved aligned image: {debug_image_path}")

    return aligned, target_pixels_per_mm, matrix


def preprocess_image(image_path: str, save_aligned: bool = False) -> Tuple[np.ndarray, float, np.ndarray]:
    """
    Load and preprocess scanned image.
    Uses alignment boxes to crop, align, and calculate accurate pixels_per_mm.

    The alignment process:
    1. Detects the 4 corner alignment boxes in the scanned image
    2. Applies perspective transformation to correct for rotation/skew
    3. Scales to standard A4 dimensions at 300 DPI
    4. After this transformation, bubble coordinates from metadata work directly!

    Returns: (binary_image, pixels_per_mm, aligned_color_image)
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Cannot load image: {image_path}")

    # Crop and align to A4 using alignment boxes
    # This handles rotation, skew, and scaling automatically
    debug_path = image_path.replace('.png', '_aligned.png') if save_aligned else None
    aligned_img, pixels_per_mm, transform_matrix = crop_and_align_to_a4(img, debug_path)

    # Convert to grayscale
    gray = cv2.cvtColor(aligned_img, cv2.COLOR_BGR2GRAY)

    # Adaptive thresholding for varying lighting conditions
    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        11, 2
    )

    return binary, pixels_per_mm, aligned_img


# BUBBLE DETECTION

def detect_bubble_fill(binary_image: np.ndarray, x_mm: float, y_mm: float,
                       pixels_per_mm: float, page_height_mm: float) -> Tuple[bool, float]:
    """
    Detect if bubble at given coordinates is filled.
    Returns: (is_filled, fill_ratio)

    Coordinates in metadata are from bottom-left, OpenCV uses top-left.
    """
    # Convert mm to pixels
    x_px = int(x_mm * pixels_per_mm)
    y_px = int((page_height_mm - y_mm) * pixels_per_mm)  # Flip Y axis

    search_radius_px = int(BUBBLE_SEARCH_RADIUS_MM * pixels_per_mm)

    # Extract region of interest
    x1 = max(0, x_px - search_radius_px)
    y1 = max(0, y_px - search_radius_px)
    x2 = min(binary_image.shape[1], x_px + search_radius_px)
    y2 = min(binary_image.shape[0], y_px + search_radius_px)

    roi = binary_image[y1:y2, x1:x2]

    if roi.size == 0:
        return False, 0.0

    # Calculate fill ratio: ratio of white pixels (marked) to total pixels
    total_pixels = roi.size
    filled_pixels = np.count_nonzero(roi)
    fill_ratio = filled_pixels / total_pixels

    is_filled = fill_ratio >= FILL_THRESHOLD

    return is_filled, fill_ratio


# RESPONSE EXTRACTION

def extract_responses(scanned_images: List[str], metadata: Dict) -> Dict[str, List[str]]:
    """
    Extract student responses from scanned images using metadata.
    Returns: {field_name: [marked_values]}
    """
    responses, _ = extract_responses_with_details(scanned_images, metadata)
    return responses


def extract_responses_with_details(scanned_images: List[str], metadata: Dict) -> Tuple[Dict[str, List[str]], List[EvaluatedBubble]]:
    """
    Extract student responses from scanned images using metadata.
    Returns: ({field_name: [marked_values]}, [all_evaluated_bubbles])
    """
    page_height_mm = metadata['page_geometry']['page_height_mm']

    # Group bubbles by page
    bubbles_by_page = {}
    for bubble in metadata['bubbles']:
        page = bubble['page']
        if page not in bubbles_by_page:
            bubbles_by_page[page] = []
        bubbles_by_page[page].append(bubble)

    # Process each page
    all_evaluated = []

    for page_num, image_path in enumerate(scanned_images, start=1):
        if page_num not in bubbles_by_page:
            continue

        # Preprocess image: alignment boxes correct rotation/skew automatically
        # After alignment, bubble coordinates from metadata work directly!
        binary_img, pixels_per_mm, aligned_color = preprocess_image(image_path)

        page_bubbles = bubbles_by_page[page_num]
        filled_count = 0

        for bubble in page_bubbles:
            # Note: No coordinate transformation needed!
            # The perspective transform already aligned the image to the metadata coordinate system
            is_filled, fill_ratio = detect_bubble_fill(
                binary_img,
                bubble['x_mm'],
                bubble['y_mm'],
                pixels_per_mm,
                page_height_mm
            )

            if is_filled:
                filled_count += 1


            all_evaluated.append(EvaluatedBubble(
                field_name=bubble['field'],
                value=bubble['value'],
                is_filled=is_filled,
                fill_ratio=fill_ratio
            ))

    # Group responses by field
    responses = {}
    for eb in all_evaluated:
        if eb.is_filled:
            if eb.field_name not in responses:
                responses[eb.field_name] = []
            responses[eb.field_name].append(eb.value)

    return responses, all_evaluated


# BUBBLE FILL ANALYSIS

def analyze_bubble_fill(all_evaluated: List[EvaluatedBubble], q_field: str) -> str:
    """
    Analyze bubble fill pattern for a question to generate debugging remark.

    Returns: A remark describing the bubble fill pattern with individual bubble fill ratios
    """
    # Get all bubbles for this question
    # Check if this is an integer type question by looking for digit fields
    digit_fields = [eb for eb in all_evaluated if eb.field_name.startswith(f"{q_field}_D")]

    if digit_fields:
        # Integer question: get all digit field bubbles
        q_bubbles = digit_fields
    else:
        # MCQ question: exact match only to avoid Q2 matching Q20, Q21, etc.
        q_bubbles = [eb for eb in all_evaluated if eb.field_name == q_field]

    if not q_bubbles:
        return "No bubbles found for question"

    # Sort bubbles by value for consistent display
    q_bubbles = sorted(q_bubbles, key=lambda x: x.value)

    # Build fill ratio details string
    fill_details = []
    for eb in q_bubbles:
        status = "✓" if eb.is_filled else "○"
        fill_details.append(f"{eb.value}:{status}({eb.fill_ratio:.2f})")

    fill_details_str = ", ".join(fill_details)

    # Count filled bubbles (above threshold)
    filled_bubbles = [eb for eb in q_bubbles if eb.is_filled]

    # Count partially filled bubbles (below threshold but > 0)
    partially_filled = [eb for eb in q_bubbles if not eb.is_filled and eb.fill_ratio > 0]

    # Count completely empty bubbles
    empty_bubbles = [eb for eb in q_bubbles if eb.fill_ratio == 0]

    # Generate remark based on patterns
    if len(filled_bubbles) > 1:
        return f"Multiple bubbles filled detected ({len(filled_bubbles)} bubbles above threshold) | Fill ratios: [{fill_details_str}]"
    elif len(filled_bubbles) == 1:
        # Check if there are also partially filled bubbles
        if len(partially_filled) > 0:
            return f"Bubble filled correctly (1 above threshold, {len(partially_filled)} partially filled detected) | Fill ratios: [{fill_details_str}]"
        else:
            return f"Bubble filled correctly | Fill ratios: [{fill_details_str}]"
    elif len(partially_filled) > 0:
        # No bubble above threshold, but some partially filled
        max_partial = max(partially_filled, key=lambda x: x.fill_ratio)
        return f"Filled bubble is not proper - very less part of bubble is filled (max: {max_partial.value}={max_partial.fill_ratio:.2f}, threshold: {FILL_THRESHOLD}) | Fill ratios: [{fill_details_str}]"
    else:
        # All bubbles are empty
        return f"No filled bubble | Fill ratios: [{fill_details_str}]"


# ANSWER KEY MATCHING & SCORING

def evaluate_responses(responses: Dict[str, List[str]], answer_key: Dict, all_evaluated: List[EvaluatedBubble] = None) -> Dict:
    """
    Compare student responses against answer key and compute score.

    answer_key structure:
    {
        'Q1': {'correct': ['A'], 'marks': 4, 'negative': 1},
        'Q2': {'correct': ['B', 'C'], 'marks': 4, 'negative': 0},  # multiple correct
        'Q31': {'correct': ['1234'], 'marks': 4, 'negative': 0},  # integer type
        ...
    }
    """
    results = {
        'total_questions': len(answer_key),
        'attempted': 0,
        'correct': 0,
        'incorrect': 0,
        'score': 0,
        'max_score': 0,
        'details': []
    }

    for q_field, q_data in answer_key.items():
        correct_answers = set(q_data['correct'])
        marks = q_data['marks']
        negative_marks = q_data.get('negative', 0)
        results['max_score'] += marks

        # For integer questions, reconstruct answer from digit fields
        if q_field.startswith('Q') and '_D' not in q_field:
            # Check if this is an integer type by looking for digit fields
            digit_fields = [f for f in responses.keys() if f.startswith(f"{q_field}_D")]

            if digit_fields:
                # Reconstruct integer from digits
                digit_fields.sort()
                student_answer = ''.join(responses.get(df, [''])[0] for df in digit_fields)
                student_answers = {student_answer} if student_answer else set()
            else:
                # MCQ type
                student_answers = set(responses.get(q_field, []))
        else:
            continue  # Skip individual digit fields

        is_attempted = len(student_answers) > 0
        is_correct = student_answers == correct_answers

        if is_attempted:
            results['attempted'] += 1

        if is_correct:
            results['correct'] += 1
            results['score'] += marks
            verdict = 'CORRECT'
        elif is_attempted:
            results['incorrect'] += 1
            results['score'] -= negative_marks
            verdict = 'INCORRECT'
        else:
            verdict = 'NOT_ATTEMPTED'

        # Generate bubble fill remark
        bubble_remark = "No bubble analysis available"
        if all_evaluated:
            bubble_remark = analyze_bubble_fill(all_evaluated, q_field)

        results['details'].append({
            'question': q_field,
            'student_answer': list(student_answers),
            'correct_answer': list(correct_answers),
            'verdict': verdict,
            'marks_awarded': marks if is_correct else (-negative_marks if is_attempted else 0),
            'bubble_filled_remark': bubble_remark
        })

    # Calculate percentage and grade
    results['percentage'] = (results['score'] / results['max_score'] * 100) if results['max_score'] > 0 else 0
    results['pass'] = results['percentage'] >= 33

    return results


# CANDIDATE INFORMATION EXTRACTION

def extract_candidate_info(responses: Dict[str, List[str]]) -> Dict[str, str]:
    """Extract candidate information from header fields (digit-wise format)"""
    candidate = {}

    # Roll number (from digit fields)
    roll_fields = sorted([f for f in responses.keys() if f.startswith('Roll No_D')])
    if roll_fields:
        roll_digits = [responses[f][0] for f in roll_fields if f in responses and responses[f]]
        candidate['roll_number'] = ''.join(roll_digits)

    # Set
    if 'Set' in responses:
        candidate['set'] = responses['Set'][0] if responses['Set'] else ''

    # Center Code (from digit fields)
    center_fields = sorted([f for f in responses.keys() if f.startswith('Center Code_D')])
    if center_fields:
        center_digits = [responses[f][0] for f in center_fields if f in responses and responses[f]]
        candidate['center_code'] = ''.join(center_digits)

    return candidate


# ANNOTATED OMR SHEET GENERATION

def create_annotated_omr(scanned_images: List[str], metadata: Dict,
                         evaluation_results: Dict, output_pdf: str):
    """
    Create annotated OMR sheet with marks, ticks/crosses for visual feedback.

    scanned_images: List of scanned image file paths
    metadata: Layout metadata from generator
    evaluation_results: Results from evaluate_responses()
    output_pdf: Output PDF path for annotated sheet
    """
    from PIL import Image
    import io
    from reportlab.lib.utils import ImageReader

    # Constants for annotations
    PAGE_WIDTH, PAGE_HEIGHT = A4
    TICK_SIZE = 4 * mm
    CROSS_SIZE = 4 * mm
    MARK_OFFSET_X = -8 * mm
    MARK_OFFSET_Y = 2 * mm

    # Create verdict lookup by question
    verdict_map = {}
    marks_map = {}
    for detail in evaluation_results['details']:
        q_num = detail['question']
        verdict_map[q_num] = detail['verdict']
        marks_map[q_num] = detail['marks_awarded']

    # Create PDF
    c = canvas.Canvas(output_pdf, pagesize=A4)

    # Process each page
    for page_num, image_path in enumerate(scanned_images, start=1):
        # Load image and apply alignment correction
        img_cv = cv2.imread(image_path)
        if img_cv is None:
            print(f"[WARNING] Cannot load image: {image_path}")
            continue

        # Align the image using alignment boxes (corrects rotation/skew)
        aligned_img, _, _ = crop_and_align_to_a4(img_cv)

        # Convert from OpenCV (BGR) to PIL (RGB)
        aligned_rgb = cv2.cvtColor(aligned_img, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(aligned_rgb)

        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Prepare for PDF
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)

        # Draw aligned scanned image as background
        # Now the image coordinates match the metadata coordinates perfectly!
        c.drawImage(ImageReader(img_buffer), 0, 0,
                   width=PAGE_WIDTH, height=PAGE_HEIGHT,
                   preserveAspectRatio=True)

        # Get questions on this page from metadata
        page_bubbles = [b for b in metadata['bubbles'] if b['page'] == page_num]

        # Group by question
        questions_on_page = set()
        for bubble in page_bubbles:
            field = bubble['field']
            # Extract question number (Q1, Q2, etc.)
            if field.startswith('Q') and not field.split('_')[0][1:].isdigit() is False:
                q_field = field.split('_')[0]  # Get Q1, Q2, etc.
                if q_field in verdict_map:
                    questions_on_page.add(q_field)

        # Draw annotations for each question
        for q_field in questions_on_page:
            # Find any bubble for this question to get position
            q_bubbles = [b for b in page_bubbles if b['field'].startswith(q_field)]
            if not q_bubbles:
                continue

            # Use first bubble's position as reference
            ref_bubble = q_bubbles[0]
            x_mm = ref_bubble['x_mm']
            y_mm = ref_bubble['y_mm']

            # Convert to PDF coordinates
            x_pdf = x_mm * mm + MARK_OFFSET_X
            y_pdf = y_mm * mm + MARK_OFFSET_Y

            verdict = verdict_map.get(q_field, 'NOT_ATTEMPTED')
            marks = marks_map.get(q_field, 0)

            # Draw tick or cross
            if verdict == 'CORRECT':
                # Draw green tick (✓)
                c.setStrokeColor(green)
                c.setLineWidth(2)
                c.line(x_pdf, y_pdf, x_pdf + TICK_SIZE * 0.4, y_pdf - TICK_SIZE * 0.6)
                c.line(x_pdf + TICK_SIZE * 0.4, y_pdf - TICK_SIZE * 0.6,
                      x_pdf + TICK_SIZE, y_pdf + TICK_SIZE * 0.4)

                # Draw marks in green
                c.setFillColor(green)
                c.setFont("Helvetica-Bold", 8)
                c.drawString(x_pdf + TICK_SIZE + 2*mm, y_pdf - 1*mm, f"+{marks}")

            elif verdict == 'INCORRECT':
                # Draw red cross (✗)
                c.setStrokeColor(red)
                c.setLineWidth(2)
                c.line(x_pdf, y_pdf, x_pdf + CROSS_SIZE, y_pdf - CROSS_SIZE)
                c.line(x_pdf + CROSS_SIZE, y_pdf, x_pdf, y_pdf - CROSS_SIZE)

                # Draw marks in red
                c.setFillColor(red)
                c.setFont("Helvetica-Bold", 8)
                c.drawString(x_pdf + CROSS_SIZE + 2*mm, y_pdf - 1*mm, f"{marks}")

            # Reset colors
            c.setStrokeColor(black)
            c.setFillColor(black)

        # Add summary at bottom of page
        c.setFont("Helvetica-Bold", 10)
        summary_y = 10 * mm
        c.drawString(15 * mm, summary_y,
                    f"Page {page_num} | Score: {evaluation_results['score']}/{evaluation_results['max_score']} | " +
                    f"Correct: {evaluation_results['correct']} | Incorrect: {evaluation_results['incorrect']}")

        c.showPage()

    c.save()
    print(f"Annotated OMR saved: {output_pdf}")


# MAIN EVALUATOR LOGIC

def evaluate_omr_sheet(scanned_images: List[str], metadata_file: str,
                       answer_key: Dict, output_results: str,
                       create_annotated: bool = True, annotated_pdf: str = None):
    """
    Main entry point: Evaluate OMR sheet and produce final results.

    scanned_images: List of image file paths (one per page) OR single PDF file path
                    - If single PDF: provide path like ['scan.pdf']
                    - If images: provide list like ['page1.jpg', 'page2.jpg']
    metadata_file: JSON file generated by generator.py
    answer_key: Dictionary mapping question fields to correct answers
    output_results: Output JSON file for results
    create_annotated: If True, create annotated OMR PDF with marks/ticks
    annotated_pdf: Output path for annotated PDF (auto-generated if None)
    """
    with open(metadata_file, 'r') as f:
        metadata = json.load(f)

    # Check if input is a PDF file
    temp_images = []
    if len(scanned_images) == 1 and scanned_images[0].lower().endswith('.pdf'):
        pdf_path = scanned_images[0]
        print(f"Converting PDF to images: {pdf_path}")
        temp_images = convert_pdf_to_images(pdf_path)
        image_files = temp_images
    else:
        image_files = scanned_images

    try:
        # Extract responses from scanned images (get raw evaluated bubbles)
        responses, all_evaluated = extract_responses_with_details(image_files, metadata)

        # Extract candidate information
        candidate_info = extract_candidate_info(responses)

        # Evaluate against answer key
        evaluation = evaluate_responses(responses, answer_key, all_evaluated)

        # Compile final results
        final_results = {
            'candidate': candidate_info,
            'evaluation': evaluation,
            'raw_responses': {k: v for k, v in responses.items() if not k.startswith('Roll No_D') and not k.startswith('Center Code_D') and k != 'Set'}
        }

        with open(output_results, 'w') as f:
            json.dump(final_results, f, indent=2)

        print(f"Score: {evaluation['score']}/{evaluation['max_score']} | Pass: {'YES' if evaluation['pass'] else 'NO'} | Output: {output_results}")

        # Create annotated OMR sheet if requested
        if create_annotated:
            if annotated_pdf is None:
                # Auto-generate annotated PDF filename
                base_name = output_results.replace('.json', '')
                annotated_pdf = f"{base_name}_annotated.pdf"

            create_annotated_omr(image_files, metadata, evaluation, annotated_pdf)

        return final_results

    finally:
        # Clean up temporary image files
        for temp_img in temp_images:
            if os.path.exists(temp_img):
                os.remove(temp_img)


if __name__ == '__main__':
    # Load answer key from JSON file
    with open('answer_key.json', 'r') as f:
        answer_key = json.load(f)
    evaluate_omr_sheet(
        scanned_images=['answer_key_rotated_15deg.png'],
        metadata_file='omr_layout.json',
        answer_key=answer_key,
        output_results='student_results.json'
    )

    # NOTE: You need to provide actual scanned image/PDF files
    # For now, this is a placeholder showing the expected usage
    print("\nTo use the evaluator, run:")
    print("  python evaluator.py")
    print("\nOption 1 - Evaluate from PDF:")
    print("  evaluate_omr_sheet(")
    print("    scanned_images=['scanned_omr.pdf'],")
    print("    metadata_file='omr_layout.json',")
    print("    answer_key=answer_key,")
    print("    output_results='student_results.json'")
    print("  )")
    print("\nOption 2 - Evaluate from images:")
    print("  evaluate_omr_sheet(")
    print("    scanned_images=['scan_page1.jpg', 'scan_page2.jpg', 'scan_page3.jpg', 'scan_page4.jpg'],")
    print("    metadata_file='omr_layout.json',")
    print("    answer_key=answer_key,")
    print("    output_results='student_results.json'")
    print("  )")
