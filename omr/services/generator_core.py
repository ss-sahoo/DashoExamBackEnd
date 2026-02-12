#!/usr/bin/env python3
"""
OMR Sheet Generator
Generates print-ready PDF OMR sheets with exact layout metadata (JSON)
"""

import json
import uuid
import barcode
from barcode.writer import ImageWriter
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from pulp import LpMinimize, LpProblem, LpVariable, lpSum, LpBinary, value
from dataclasses import dataclass
from typing import List, Dict, Tuple



# FIXED PAGE GEOMETRY (Constants)


PAGE_WIDTH, PAGE_HEIGHT = A4  # 595.27 x 841.89 points

MARGIN_TOP = 15 * mm
MARGIN_BOTTOM = 5 * mm
MARGIN_LEFT = 5 * mm
MARGIN_RIGHT = 5 * mm

USABLE_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT
USABLE_HEIGHT = PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM

BUBBLE_RADIUS = 1.75 * mm 
BUBBLE_VERTICAL_SPACING = 0.4 * mm

# Bubble and text colors (RGB values 0-1)
BUBBLE_COLOR = (0, 0, 0)  # Black
BUBBLE_TEXT_COLOR = (0, 0, 0)  # Black

FIELD_HEIGHT_OPTIONS = 6 * mm
FIELD_HEIGHT_DIGITS = 2*FIELD_HEIGHT_OPTIONS + 29 * mm  + 2 * mm# Height for title and box + digit hieght + one more height equal of title
QUESTION_HEIGHT_MCQ = 4 * mm
QUESTION_HEIGHT_INTEGER = 2*QUESTION_HEIGHT_MCQ + 29 * mm + 2 * mm # Height for title and box + digit hieght + one more height equal of title + 2mm row spacing
SECTION_HEADER_HEIGHT = 10 * mm

SUBSECTION_HEADER_HEIGHT = 4 * mm

INSTRUCTIONS_BOX_HEIGHT = 18 * mm
SIGNATURE_BOX_HEIGHT = 12 * mm
MIN_FIELD_WIDTH = 14 * mm
MIN_QUESTION_WIDTH = 15 * mm

DEBUG_DRAW_BLOCKS = False



# BLOCK ABSTRACTION


@dataclass
class Block:
    """Fundamental layout abstraction - fixed height, semantic identity"""
    height: float
    width: float
    block_type: str  # 'header', 'section_header', 'questions'
    content: Dict
    x_offset: float = 0


@dataclass
class BubbleMetadata:
    """Exact coordinates and semantic meaning of each bubble"""
    page: int
    x: float  # mm from page left edge
    y: float  # mm from page bottom edge
    field_name: str
    value: str  # option label or digit

@dataclass
class DrawingElement:
    """Track all drawing elements to detect overlaps"""
    page: int
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    element_type: str
    label: str

class CoordinateTracker:
    """Global coordinate system to track all drawings"""
    def __init__(self):
        self.elements = []

    def add_element(self, page: int, x_min: float, y_min: float, x_max: float, y_max: float,
                   element_type: str, label: str = ""):
        element = DrawingElement(page, x_min, y_min, x_max, y_max, element_type, label)

        for existing in self.elements:
            if existing.page != page:
                continue

            horizontal_overlap = not (x_max <= existing.x_min or x_min >= existing.x_max)
            vertical_overlap = not (y_max <= existing.y_min or y_min >= existing.y_max)

            if horizontal_overlap and vertical_overlap:
                print(f"[OVERLAP WARNING] {element_type} '{label}' at ({x_min/mm:.2f},{y_min/mm:.2f}) overlaps with {existing.element_type} '{existing.label}' at ({existing.x_min/mm:.2f},{existing.y_min/mm:.2f})")

        self.elements.append(element)

# PHASE 1: HORIZONTAL LAYOUT OPTIMIZATION

def solve_2d_strip_packing_ilp(items, strip_width, spacing=3*mm, vertical_spacing=3*mm):
    """
    Solve 2D Strip Packing Problem using ILP to minimize total height.
    Items can be placed anywhere as long as they don't overlap and fit within width.
    Items are packed from left to right.

    Decision Variables:
    - x_i: horizontal position of item i
    - y_i: vertical position of item i
    - H: total height of the strip
    - left_ij, right_ij, above_ij, below_ij: binary variables for no-overlap constraints

    Parameters:
    - spacing: horizontal gap between items in same row
    - vertical_spacing: vertical gap between rows
    """
    n = len(items)
    if n == 0:
        return []

    sorted_items = sorted(enumerate(items), key=lambda x: x[1]['name'])
    item_order = [idx for idx, _ in sorted_items]
    items = [item for _, item in sorted_items]

    M = 10000

    prob = LpProblem("2D_Strip_Packing", LpMinimize)

    x = {i: LpVariable(f"x_{i}", 0, strip_width) for i in range(n)}
    y = {i: LpVariable(f"y_{i}", 0, M) for i in range(n)}
    H = LpVariable("H", 0, M)

    left = {}
    right = {}
    above = {}
    below = {}

    for i in range(n):
        for j in range(i + 1, n):
            left[(i, j)] = LpVariable(f"left_{i}_{j}", cat=LpBinary)
            right[(i, j)] = LpVariable(f"right_{i}_{j}", cat=LpBinary)
            above[(i, j)] = LpVariable(f"above_{i}_{j}", cat=LpBinary)
            below[(i, j)] = LpVariable(f"below_{i}_{j}", cat=LpBinary)

    prob += H + 0.001 * lpSum([x[i] for i in range(n)])

    for i in range(n):
        prob += x[i] + items[i]['width'] <= strip_width

    for i in range(n):
        prob += y[i] + items[i]['height'] <= H

    # Binary variable to track if items are on the same row
    same_row = {}
    for i in range(n):
        for j in range(i + 1, n):
            same_row[(i, j)] = LpVariable(f"same_row_{i}_{j}", cat=LpBinary)

    for i in range(n):
        for j in range(i + 1, n):
            prob += x[i] + items[i]['width'] + spacing <= x[j] + M * (1 - left[(i, j)])
            prob += x[j] + items[j]['width'] + spacing <= x[i] + M * (1 - right[(i, j)])
            prob += y[i] + items[i]['height'] + vertical_spacing <= y[j] + M * (1 - above[(i, j)])
            prob += y[j] + items[j]['height'] + vertical_spacing <= y[i] + M * (1 - below[(i, j)])

            prob += left[(i, j)] + right[(i, j)] + above[(i, j)] + below[(i, j)] >= 1

            # If items are on the same row (neither above nor below each other), enforce left-to-right order
            # same_row is 1 when both above and below are 0
            prob += same_row[(i, j)] <= 1 - above[(i, j)]
            prob += same_row[(i, j)] <= 1 - below[(i, j)]
            prob += same_row[(i, j)] >= 1 - above[(i, j)] - below[(i, j)] - 0.5

            # If on same row, item i must be to the left of item j (alphabetical order)
            prob += x[i] + items[i]['width'] + spacing <= x[j] + M * (1 - same_row[(i, j)])

    prob.solve()

    if prob.status != 1:
        return None

    placements = []
    for i in range(n):
        placements.append({
            'item': items[i],
            'x': value(x[i]),
            'y': value(y[i]),
            'original_index': item_order[i]
        })

    placements.sort(key=lambda p: (p['y'], p['x']))

    result = []
    for p in placements:
        result.append({
            'item': p['item'],
            'x': p['x'],
            'y': p['y']
        })

    total_height = value(H)

    return result, total_height

def optimize_header_layout(candidate_fields: List[Dict]) -> Block:
    """
    Arrange candidate fields using ILP for 2D Strip Packing to minimize height.
    """
    print("\n[HEADER LAYOUT OPTIMIZATION - ILP]")

    items = []
    for idx, field in enumerate(candidate_fields):
        field_type = field.get('type', 'options')
        field_height = FIELD_HEIGHT_DIGITS if field_type == 'digits' else FIELD_HEIGHT_OPTIONS

        if field_type == 'digits':
            field_width = 12*mm + field['digits'] * 4.5*mm + 5*mm
        else:
            field_width = 12*mm + len(field['options']) * 4.5*mm + 5*mm

        items.append({
            'name': field['name'],
            'type': field_type,
            'options': field.get('options', []),
            'digits': field.get('digits', 0),
            'width': field_width,
            'height': field_height,
            'index': idx
        })
        print(f"  Block {idx}: '{field['name']}' width={field_width/mm:.2f}mm, height={field_height/mm:.2f}mm")

    print(f"  Strip width constraint: {USABLE_WIDTH/mm:.2f}mm")
    print(f"  Solving ILP for 2D Strip Packing...")

    result = solve_2d_strip_packing_ilp(items, USABLE_WIDTH, spacing=3*mm, vertical_spacing=3*mm)

    if result is None:
        print(f"  ILP failed, using simple greedy fallback")
        sorted_items = sorted(items, key=lambda x: x['height'], reverse=True)
        arranged_fields = []
        y_offset = 0
        for item in sorted_items:
            arranged_fields.append({
                'name': item['name'],
                'type': item['type'],
                'options': item['options'],
                'digits': item['digits'],
                'x_offset': 0,
                'y_offset': y_offset,
                'width': item['width'],
                'height': item['height']
            })
            y_offset += itetotal_heightm['height']
        total_height = y_offset
        max_width = max(item['width'] for item in items)
    else:
        placement, total_height = result
        print(f"  ILP optimal height: {total_height/mm:.2f}mm")

        arranged_fields = []
        max_width = 0
        for p in placement:
            item = p['item']
            arranged_fields.append({
                'name': item['name'],
                'type': item['type'],
                'options': item['options'],
                'digits': item['digits'],
                'x_offset': p['x'],
                'y_offset': p['y'],
                'width': item['width'],
                'height': item['height']
            })
            max_width = max(max_width, p['x'] + item['width'])
            print(f"    '{item['name']}' placed at x={p['x']/mm:.2f}mm, y={p['y']/mm:.2f}mm")

    print(f"  Total header block: width={max_width/mm:.2f}mm, height={total_height/mm:.2f}mm\n")

    return Block(
        height=total_height,
        width=max_width,
        block_type='header',
        content={'fields': arranged_fields}
    )


def optimize_question_layout(questions: List[Dict], question_type: str) -> Block:
    """
    Arrange questions in multiple columns to minimize rows.
    Returns a composite block with optimized column layout.
    Height is based on question type (integer questions need more vertical space for bubbles).
    """
    num_questions = len(questions)

    if question_type == 'integer':
        # Width calculation: question number starts at -0.5mm, bubbles start at 8mm
        # Added 1.5mm to account for question number repositioning from +1mm to -0.5mm
        question_width = 9.5*mm + questions[0]['digits'] * 4.5*mm + 3*mm
        question_height = QUESTION_HEIGHT_INTEGER
    else:
        # Width calculation: question number starts at -0.5mm, bubbles start at 8mm
        # Added 1.5mm to account for question number repositioning from +1mm to -0.5mm
        question_width = 9.5*mm + len(questions[0]['options']) * 4.5*mm + 3*mm
        question_height = QUESTION_HEIGHT_MCQ

    max_cols = max(1, int(USABLE_WIDTH / question_width))
    cols = min(max_cols, num_questions)

    rows = (num_questions + cols - 1) // cols
    total_height = rows * question_height

    arranged_questions = []
    for i, q in enumerate(questions):
        row = i // cols
        col = i % cols
        arranged_questions.append({
            'number': q['number'],
            'type': question_type,
            'options': q.get('options', []),
            'digits': q.get('digits', 0),
            'row': row,
            'col': col,
            'cols_in_row': cols,
            'height': question_height
        })

    block_width = cols * question_width

    return Block(
        height=total_height,
        width=block_width,
        block_type='questions',
        content={'questions': arranged_questions, 'rows': rows, 'cols': cols, 'question_height': question_height}
    )



# PHASE 2: VERTICAL PAGINATION


def check_overlaps(pages: List[List[Block]]) -> bool:
    has_overlap = False
    for page_num, page_blocks in enumerate(pages, start=1):
        for i, block in enumerate(page_blocks):
            block_top = PAGE_HEIGHT - MARGIN_TOP - block.y_offset
            block_bottom = block_top - block.height
            block_left = MARGIN_LEFT + block.x_offset
            block_right = block_left + block.width

            for j, other_block in enumerate(page_blocks):
                if i >= j:
                    continue

                other_top = PAGE_HEIGHT - MARGIN_TOP - other_block.y_offset
                other_bottom = other_top - other_block.height
                other_left = MARGIN_LEFT + other_block.x_offset
                other_right = other_left + other_block.width

                horizontal_overlap = not (block_right <= other_left or block_left >= other_right)
                vertical_overlap = not (block_bottom >= other_top or block_top <= other_bottom)

                if horizontal_overlap and vertical_overlap:
                    has_overlap = True
                    print(f"[OVERLAP DETECTED] Page {page_num}: Block {i} ({block.block_type}, y_offset={block.y_offset/mm:.2f}mm) overlaps with Block {j} ({other_block.block_type}, y_offset={other_block.y_offset/mm:.2f}mm)")

    return has_overlap

def split_block(block: Block, available_height: float) -> Tuple[Block, Block]:
    """Split a block with rows into two parts if it doesn't fit in available space

    This function handles splitting of blocks that have a row-based structure,
    allowing partial rendering to fill remaining page space efficiently.

    Currently supports splitting of 'questions' block type. Can be extended
    to support other block types that have multiple rows (e.g., header blocks,
    instruction blocks) by adding additional conditional branches.

    Args:
        block: The block to potentially split
        available_height: Height available on current page

    Returns:
        (first_part, second_part) where first_part fits in available_height,
        or (None, block) if the block cannot be split or already fits.
    """
    # Only questions blocks support splitting (they have row structure)
    if block.block_type != 'questions':
        return None, block

    content = block.content

    # Check if block has the required row structure
    if 'question_height' not in content or 'rows' not in content or 'cols' not in content:
        return None, block

    question_height = content['question_height']
    cols = content['cols']
    total_rows = content['rows']

    # Calculate how many complete rows fit in available space
    rows_that_fit = max(1, int(available_height / question_height))

    # If all rows fit, no need to split
    if rows_that_fit >= total_rows:
        return None, block

    # Split the questions list
    questions = content['questions']
    questions_that_fit = rows_that_fit * cols

    first_part_questions = questions[:questions_that_fit]
    second_part_questions = questions[questions_that_fit:]

    # Recalculate row indices for first part
    for i, q in enumerate(first_part_questions):
        q['row'] = i // cols

    # Recalculate row indices for second part
    for i, q in enumerate(second_part_questions):
        q['row'] = i // cols

    # Create first block that fits in available space
    first_block = Block(
        height=rows_that_fit * question_height,
        width=block.width,
        block_type='questions',
        content={
            'questions': first_part_questions,
            'rows': rows_that_fit,
            'cols': cols,
            'question_height': question_height
        }
    )

    # Create second block with remaining questions
    remaining_rows = (len(second_part_questions) + cols - 1) // cols
    second_block = Block(
        height=remaining_rows * question_height,
        width=block.width,
        block_type='questions',
        content={
            'questions': second_part_questions,
            'rows': remaining_rows,
            'cols': cols,
            'question_height': question_height
        }
    )

    return first_block, second_block

def paginate_blocks(blocks: List[Block]) -> List[List[Block]]:
    pages = []
    current_page = []
    current_y = 0
    current_row_blocks = []
    current_row_x = 0
    current_row_height = 0
    min_spacing = 2*mm

    i = 0
    while i < len(blocks):
        block = blocks[i]
        can_fit_horizontally = current_row_x + block.width <= USABLE_WIDTH
        can_fit_vertically = current_y + max(current_row_height, block.height) + min_spacing <= USABLE_HEIGHT

        if can_fit_horizontally and (current_row_height == 0 or current_row_height == block.height or can_fit_vertically):
            block.x_offset = current_row_x
            block.y_offset = current_y
            current_row_blocks.append(block)
            current_row_x += block.width + min_spacing
            current_row_height = max(current_row_height, block.height)
            i += 1
        else:
            if current_row_blocks:
                for rb in current_row_blocks:
                    rb.y_offset = current_y
                current_page.extend(current_row_blocks)
                current_y += current_row_height + min_spacing
                current_row_blocks = []
                current_row_x = 0
                current_row_height = 0

            if current_y + block.height + min_spacing <= USABLE_HEIGHT:
                block.x_offset = 0
                block.y_offset = current_y
                current_row_blocks.append(block)
                current_row_x = block.width + min_spacing
                current_row_height = block.height
                i += 1
            else:
                available_height = USABLE_HEIGHT - current_y
                first_part, second_part = split_block(block, available_height)

                if first_part:
                    first_part.x_offset = 0
                    first_part.y_offset = current_y
                    current_page.append(first_part)

                    if current_page:
                        pages.append(current_page)
                    current_page = []
                    current_y = 0

                    blocks[i] = second_part
                else:
                    if current_page:
                        pages.append(current_page)
                    current_page = []
                    current_y = 0
                    block.x_offset = 0
                    block.y_offset = 0
                    current_row_blocks = [block]
                    current_row_x = block.width + min_spacing
                    current_row_height = block.height
                    i += 1

    if current_row_blocks:
        for rb in current_row_blocks:
            rb.y_offset = current_y
        current_page.extend(current_row_blocks)
    if current_page:
        pages.append(current_page)

    print(f"[PAGINATION] Blocks={len(blocks)}, Pages={len(pages)}")

    if check_overlaps(pages):
        print("[WARNING] Overlaps detected, adjusting spacing...")

    return pages



# PDF RENDERING & METADATA GENERATION


def draw_bubble(c: canvas.Canvas, x: float, y: float):
    """Draw a single OMR bubble circle"""
    c.setStrokeColorRGB(*BUBBLE_COLOR)
    c.circle(x, y, BUBBLE_RADIUS, stroke=1, fill=0)
    c.setStrokeColorRGB(0, 0, 0)


def draw_alignment_boxes(c: canvas.Canvas):
    """Draw black alignment boxes at the four corners of the A4 sheet for OMR scanning alignment

    These boxes are positioned at the absolute corners of the page (0,0) and (PAGE_WIDTH, PAGE_HEIGHT)
    to allow accurate calibration of pixel-to-mm conversion during scanning.
    """
    box_size = 5 * mm  # Size of alignment boxes (5mm x 5mm)

    # Top-left corner (absolute corner of page)
    c.setFillColorRGB(0, 0, 0)
    c.rect(0, PAGE_HEIGHT - box_size, box_size, box_size, fill=1, stroke=0)

    # Top-right corner (absolute corner of page)
    c.rect(PAGE_WIDTH - box_size, PAGE_HEIGHT - box_size, box_size, box_size, fill=1, stroke=0)

    # Bottom-left corner (absolute corner of page)
    c.rect(0, 0, box_size, box_size, fill=1, stroke=0)

    # Bottom-right corner (absolute corner of page)
    c.rect(PAGE_WIDTH - box_size, 0, box_size, box_size, fill=1, stroke=0)

    c.setFillColorRGB(0, 0, 0)  # Reset to black


def render_header_block(c: canvas.Canvas, block: Block, y_start: float, page_num: int, metadata: List[BubbleMetadata], tracker: CoordinateTracker = None):
    fields = block.content['fields']
    field_label_spacing = 3*mm
    label_to_content_spacing = 4*mm
    min_y_content = y_start

    for field_data in fields:
        y_offset = field_data['y_offset']
        x_base = MARGIN_LEFT + block.x_offset + field_data['x_offset']
        y_base = y_start - y_offset

        c.setFont("Helvetica-Bold", 7)
        label_text = field_data['name']
        label_width = c.stringWidth(label_text, "Helvetica-Bold", 7)
        c.drawString(x_base, y_base - field_label_spacing, label_text)

        if tracker:
            tracker.add_element(page_num, x_base, y_base - field_label_spacing - 2*mm,
                              x_base + label_width, y_base - field_label_spacing + 2*mm,
                              "field_label", field_data['name'])

        content_start_x = x_base + label_width + label_to_content_spacing

        if field_data['type'] == 'digits':
            num_digits = field_data['digits']
            digit_spacing = 4.5*mm
            box_size = 4*mm

            c.setFont("Helvetica", 6)
            for digit_pos in range(num_digits):
                box_x = content_start_x + digit_pos * digit_spacing
                box_y = y_base - field_label_spacing
                c.rect(box_x - box_size/2, box_y - box_size/2, box_size, box_size)

                if tracker:
                    tracker.add_element(page_num, box_x - box_size/2, box_y - box_size/2,
                                      box_x + box_size/2, box_y + box_size/2,
                                      "digit_box", f"{field_data['name']}_box_{digit_pos}")

            bubble_start_y = y_base - field_label_spacing - box_size - 1*mm
            for digit_pos in range(num_digits):
                for digit_val in range(10):
                    bubble_x = content_start_x + digit_pos * digit_spacing
                    bubble_y = bubble_start_y - digit_val * (2 * BUBBLE_RADIUS + BUBBLE_VERTICAL_SPACING)

                    draw_bubble(c, bubble_x, bubble_y)
                    c.setFillColorRGB(*BUBBLE_TEXT_COLOR)
                    c.drawString(bubble_x - 0.7*mm, bubble_y - 0.7*mm, str(digit_val))
                    c.setFillColorRGB(0, 0, 0)

                    min_y_content = min(min_y_content, bubble_y - BUBBLE_RADIUS)

                    if tracker:
                        tracker.add_element(page_num, bubble_x - BUBBLE_RADIUS, bubble_y - BUBBLE_RADIUS,
                                          bubble_x + BUBBLE_RADIUS, bubble_y + BUBBLE_RADIUS,
                                          "bubble", f"{field_data['name']}_D{digit_pos}_{digit_val}")

                    metadata.append(BubbleMetadata(
                        page=page_num,
                        x=bubble_x / mm,
                        y=bubble_y / mm,
                        field_name=f"{field_data['name']}_D{digit_pos}",
                        value=str(digit_val)
                    ))
        else:
            options = field_data['options']
            bubble_spacing = 4.5*mm

            bubble_y = y_base - field_label_spacing - 1*mm
            c.setFont("Helvetica", 7)
            for i, option in enumerate(options):
                bubble_x = content_start_x + i * bubble_spacing

                draw_bubble(c, bubble_x, bubble_y)
                c.setFillColorRGB(*BUBBLE_TEXT_COLOR)
                c.drawString(bubble_x - 0.8*mm, bubble_y - 0.8*mm, str(option))
                c.setFillColorRGB(0, 0, 0)

                min_y_content = min(min_y_content, bubble_y - BUBBLE_RADIUS)

                if tracker:
                    tracker.add_element(page_num, bubble_x - BUBBLE_RADIUS, bubble_y - BUBBLE_RADIUS,
                                      bubble_x + BUBBLE_RADIUS, bubble_y + BUBBLE_RADIUS,
                                      "bubble", f"{field_data['name']}_{option}")

                metadata.append(BubbleMetadata(
                    page=page_num,
                    x=bubble_x / mm,
                    y=bubble_y / mm,
                    field_name=field_data['name'],
                    value=str(option)
                ))

    # Removed line separator between header and questions


def render_response_header(c: canvas.Canvas, block: Block, y_start: float):
    """Render the 'Response' section header at the top of questions"""
    c.setFont("Helvetica-Bold", 9)
    c.drawString(MARGIN_LEFT + block.x_offset, y_start - 3*mm, "Response")


def render_section_header(c: canvas.Canvas, block: Block, y_start: float):
    section_name = block.content['name']
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN_LEFT + block.x_offset, y_start - 4*mm, section_name.upper())
    c.setLineWidth(1)
    c.line(MARGIN_LEFT + block.x_offset, y_start - 5*mm, MARGIN_LEFT + block.x_offset + block.width, y_start - 5*mm)



def render_subsection_header(c: canvas.Canvas, block: Block, y_start: float):
    subsection_name = block.content['name']
    c.setFont("Helvetica-Bold", 7)
    c.drawString(MARGIN_LEFT + block.x_offset + 1*mm, y_start - 2*mm, subsection_name)


def render_instructions_box(c: canvas.Canvas, block: Block, y_start: float):
    """Render instructions box with OMR filling guidelines"""
    x_start = MARGIN_LEFT + block.x_offset
    box_width = block.width
    box_height = block.height

    c.rect(x_start, y_start - box_height, box_width, box_height)

    c.setFont("Helvetica-Bold", 6)
    c.drawString(x_start + 1*mm, y_start - 2.5*mm, "INSTRUCTIONS")

    instructions_col1 = [
        "• Fill all required details.",
        "• Use black or blue pen.",
        "• Do not use gel/ink pen."
    ]

    instructions_col2 = [
        "• Shade bubble completely.",
        "• No tick/cross/half shade.",
        "• Do not change answer."
    ]

    instructions_col3 = [
        "• Write in given boxes.",
        "• No extra marks on sheet.",
        "• No whitener/eraser."
    ]

    instructions_col4 = [
        "• Do not fold/tear sheet.",
        "• Sign in given space.",
        "• Ensure invigilator signs."
    ]

    c.setFont("Helvetica", 5)

    all_instructions = [
        instructions_col1,
        instructions_col2,
        instructions_col3,
        instructions_col4
    ]

    num_cols = len(all_instructions)
    col_width = (box_width - 2*mm) / num_cols

    col_positions = []
    for i in range(num_cols):
        col_positions.append(x_start + 1*mm + i * col_width)

    y_text = y_start - 5.5*mm
    line_spacing = 3*mm

    for col_idx, col_instructions in enumerate(all_instructions):
        y_temp = y_text
        for instruction in col_instructions:
            c.drawString(col_positions[col_idx], y_temp, instruction)
            y_temp -= line_spacing

    examples_x = x_start + 1*mm
    examples_y = y_start - box_height + 3.5*mm

    c.setFont("Helvetica-Bold", 5)
    c.drawString(examples_x, examples_y, "EXAMPLES:")

    c.setFont("Helvetica-Bold", 4.5)
    c.setFillColorRGB(0, 0.65, 0)
    c.drawString(examples_x + 17*mm, examples_y, "Correct:")

    bubble_x = examples_x + 30*mm
    bubble_y = examples_y - 0.5*mm
    c.setFillColorRGB(0, 0, 0)
    c.circle(bubble_x, bubble_y, BUBBLE_RADIUS, stroke=1, fill=1)

    c.setFont("Helvetica-Bold", 4.5)
    c.setFillColorRGB(0.85, 0, 0)
    c.drawString(examples_x + 37*mm, examples_y, "Incorrect:")
    c.setFillColorRGB(0, 0, 0)

    bubble_x = examples_x + 54*mm
    c.circle(bubble_x, bubble_y, BUBBLE_RADIUS, stroke=1, fill=0)
    c.setLineWidth(0.4)
    c.setStrokeColorRGB(0, 0, 0)
    c.line(bubble_x - 0.8*mm, bubble_y - 0.3*mm, bubble_x - 0.2*mm, bubble_y - 0.8*mm)
    c.line(bubble_x - 0.2*mm, bubble_y - 0.8*mm, bubble_x + 0.8*mm, bubble_y + 0.8*mm)

    bubble_x += 3.5*mm
    c.circle(bubble_x, bubble_y, BUBBLE_RADIUS, stroke=1, fill=0)
    c.line(bubble_x - 0.8*mm, bubble_y - 0.8*mm, bubble_x + 0.8*mm, bubble_y + 0.8*mm)
    c.line(bubble_x - 0.8*mm, bubble_y + 0.8*mm, bubble_x + 0.8*mm, bubble_y - 0.8*mm)

    bubble_x += 3.5*mm
    c.circle(bubble_x, bubble_y, BUBBLE_RADIUS, stroke=1, fill=0)
    c.setLineWidth(0.5)
    c.arc(bubble_x - BUBBLE_RADIUS, bubble_y - BUBBLE_RADIUS,
          bubble_x + BUBBLE_RADIUS, bubble_y + BUBBLE_RADIUS, 85, 185)

    bubble_x += 3.5*mm
    c.circle(bubble_x, bubble_y, BUBBLE_RADIUS, stroke=1, fill=0)
    c.setLineWidth(0.3)
    c.circle(bubble_x, bubble_y, BUBBLE_RADIUS * 0.55, stroke=0, fill=1)

    bubble_x += 3.5*mm
    c.circle(bubble_x, bubble_y, BUBBLE_RADIUS, stroke=1, fill=0)
    c.saveState()
    c.translate(bubble_x + 0.45*mm, bubble_y - 0.35*mm)
    c.rotate(22)
    c.scale(0.7, 1.15)
    c.circle(0, 0, BUBBLE_RADIUS, stroke=0, fill=1)
    c.restoreState()

    c.setLineWidth(1)
    c.setStrokeColorRGB(0, 0, 0)
    c.setFillColorRGB(0, 0, 0)


def render_signature_boxes(c: canvas.Canvas, block: Block, y_start: float):
    x_start = MARGIN_LEFT + block.x_offset
    box_width = block.width / 2 - 2*mm
    box_height = block.height + 1*mm
    y_start = y_start - 1*mm

    c.rect(x_start, y_start - box_height, box_width, box_height)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x_start + 1*mm, y_start - 4*mm, "Examinee Signature:")
    c.setFont("Helvetica", 6)
    c.drawString(x_start + 1*mm, y_start - box_height + 2*mm, "(Sign within the box)")

    x_invigilator = x_start + box_width + 4*mm
    c.rect(x_invigilator, y_start - box_height, box_width, box_height)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x_invigilator + 1*mm, y_start - 4*mm, "Invigilator Signature:")
    c.setFont("Helvetica", 6)
    c.drawString(x_invigilator + 1*mm, y_start - box_height + 2*mm, "(Sign within the box)")


def render_question_block(c: canvas.Canvas, block: Block, y_start: float, page_num: int, metadata: List[BubbleMetadata]):
    questions = block.content['questions']
    cols = block.content['cols']
    question_height = block.content['question_height']

    for q_data in questions:
        row = q_data['row']
        col = q_data['col']

        col_width = block.width / cols
        x_base = MARGIN_LEFT + block.x_offset + col * col_width
        y_base = y_start - row * question_height

        if q_data['type'] == 'integer':
            num_digits = q_data['digits']
            digit_spacing = 4.5*mm

            c.setFont("Helvetica-Bold", 7)
            c.drawString(x_base - 0.5*mm, y_base - 3.1*mm, f"Q{q_data['number']}") # edited to match the alignment of bubble

            c.setFont("Helvetica", 6)
            for digit_pos in range(num_digits):
                for digit_val in range(10):
                    bubble_x = x_base + 8*mm + digit_pos * digit_spacing
                    bubble_y = y_base - 2.5*mm - digit_val * (2 * BUBBLE_RADIUS + BUBBLE_VERTICAL_SPACING)

                    draw_bubble(c, bubble_x, bubble_y)
                    c.setFillColorRGB(*BUBBLE_TEXT_COLOR)
                    c.drawString(bubble_x - 0.7*mm, bubble_y - 0.7*mm, str(digit_val))
                    c.setFillColorRGB(0, 0, 0)

                    metadata.append(BubbleMetadata(
                        page=page_num,
                        x=bubble_x / mm,
                        y=bubble_y / mm,
                        field_name=f"Q{q_data['number']}_D{digit_pos}",
                        value=str(digit_val)
                    ))
        else:
            options = q_data['options']
            bubble_spacing = 4.5*mm

            c.setFont("Helvetica-Bold", 7)
            bubble_y = y_base - 2.5*mm
            c.drawString(x_base - 0.5*mm, bubble_y - 0.6*mm, f"Q{q_data['number']}") # edited to match the alignment of bubble

            c.setFont("Helvetica", 7)
            for i, option in enumerate(options):
                bubble_x = x_base + 8*mm + i * bubble_spacing

                draw_bubble(c, bubble_x, bubble_y)
                c.setFillColorRGB(*BUBBLE_TEXT_COLOR)
                c.drawString(bubble_x - 0.8*mm, bubble_y - 0.8*mm, option)
                c.setFillColorRGB(0, 0, 0)

                metadata.append(BubbleMetadata(
                    page=page_num,
                    x=bubble_x / mm,
                    y=bubble_y / mm,
                    field_name=f"Q{q_data['number']}",
                    value=option
                ))


def generate_barcode(sheet_id: str) -> ImageReader:
    """Generate barcode image for unique sheet identification"""
    CODE128 = barcode.get_barcode_class('code128')

    barcode_buffer = BytesIO()
    barcode_instance = CODE128(sheet_id, writer=ImageWriter())
    barcode_instance.write(barcode_buffer, options={
        'module_width': 0.3,
        'module_height': 8,
        'quiet_zone': 2,
        'font_size': 8,
        'text_distance': 2
    })
    barcode_buffer.seek(0)

    return ImageReader(barcode_buffer)


def render_pages(pages: List[List[Block]], output_pdf: str, metadata: List[BubbleMetadata], sheet_id: str):
    """Render all pages to PDF and generate complete metadata"""
    c = canvas.Canvas(output_pdf, pagesize=A4)
    tracker = CoordinateTracker()

    barcode_img = generate_barcode(sheet_id)
    barcode_width = 60 * mm
    barcode_height = 12 * mm

    for page_num, page_blocks in enumerate(pages, start=1):
        # Draw alignment boxes at four corners
        draw_alignment_boxes(c)

        # Center the barcode horizontally at the top
        barcode_x = (PAGE_WIDTH - barcode_width) / 2
        barcode_y = PAGE_HEIGHT - MARGIN_TOP + 2 * mm
        c.drawImage(barcode_img, barcode_x, barcode_y, width=barcode_width, height=barcode_height)

        for block in page_blocks:
            y_start = PAGE_HEIGHT - MARGIN_TOP - block.y_offset

            if DEBUG_DRAW_BLOCKS:
                c.setStrokeColorRGB(1, 0, 0)
                c.setLineWidth(0.5)
                c.rect(MARGIN_LEFT + block.x_offset, y_start - block.height, block.width, block.height)
                c.setStrokeColorRGB(0, 0, 0)
                c.setLineWidth(1)

            if block.block_type == 'header':
                render_header_block(c, block, y_start, page_num, metadata, tracker)
            elif block.block_type == 'response_header':
                render_response_header(c, block, y_start)
            elif block.block_type == 'section_header':
                render_section_header(c, block, y_start)
            elif block.block_type == 'subsection_header':
                render_subsection_header(c, block, y_start)
            elif block.block_type == 'instructions':
                render_instructions_box(c, block, y_start)
            elif block.block_type == 'signatures':
                render_signature_boxes(c, block, y_start)
            elif block.block_type == 'questions':
                render_question_block(c, block, y_start, page_num, metadata)

        c.showPage()

    c.save()



# MAIN GENERATOR LOGIC

def create_omr_blocks(exam_config: Dict) -> List[Block]:
    """
    Create OMR layout blocks from exam configuration.
    This function is shared between generate_omr_sheet and generate_answer_key_sheet
    to ensure identical layouts.

    Returns: List of Block objects ready for pagination
    """
    blocks = []

    # Add instructions box at the top
    blocks.append(Block(
        height=INSTRUCTIONS_BOX_HEIGHT,
        width=USABLE_WIDTH,
        block_type='instructions',
        content={}
    ))

    # Phase 1A: Optimize candidate information header
    if 'candidate_fields' in exam_config:
        header_block = optimize_header_layout(exam_config['candidate_fields'])
        blocks.append(header_block)
        blocks.append(Block(
            height=3*mm,
            width=USABLE_WIDTH,
            block_type='spacing',
            content={}
        ))

    # Phase 1B: Optimize questions section-wise

    for section in exam_config.get('sections', []):
        # Add section header
        if section.get('name'):
            blocks.append(Block(
                height=SECTION_HEADER_HEIGHT,
                width=USABLE_WIDTH,
                block_type='section_header',
                content={'name': section['name']}
            ))

        for group in section.get('question_groups', []):
            question_type = group['type']

            question_block = optimize_question_layout(
                group['questions'],
                question_type
            )
            blocks.append(question_block)
        
        # Add a small spacing after each section
        blocks.append(Block(
            height=2 * mm,
            width=USABLE_WIDTH,
            block_type='spacing',
            content={}
        ))


    # Add signature boxes at the end
    blocks.append(Block(
        height=SIGNATURE_BOX_HEIGHT,
        width=USABLE_WIDTH,
        block_type='signatures',
        content={}
    ))

    return blocks


def generate_omr_sheet(exam_config: Dict, output_pdf: str, output_metadata: str, sheet_id: str = None):
    """
    Main entry point: Generate OMR sheet PDF and layout metadata JSON.

    exam_config structure:
    {
        'candidate_fields': [{'name': 'Roll No', 'options': [0,1,2,...,9]}, ...],
        'sections': [
            {
                'name': 'Physics',
                'question_groups': [
                    {'type': 'mcq', 'questions': [{'number': 1, 'options': ['A','B','C','D']}, ...]},
                    {'type': 'integer', 'questions': [{'number': 31, 'digits': 4}, ...]}
                ]
            },
            ...
        ]
    }
    sheet_id: Unique identifier for this OMR sheet (auto-generated if not provided)
    """
    if sheet_id is None:
        sheet_id = str(uuid.uuid4())[:12].upper()

    # Create blocks using shared function
    blocks = create_omr_blocks(exam_config)

    # Phase 2: Vertical pagination
    pages = paginate_blocks(blocks)

    # Render PDF and generate metadata
    metadata = []
    render_pages(pages, output_pdf, metadata, sheet_id)

    # Save metadata as JSON
    metadata_dict = {
        'sheet_id': sheet_id,
        'total_pages': len(pages),
        'page_geometry': {
            'page_width_mm': PAGE_WIDTH / mm,
            'page_height_mm': PAGE_HEIGHT / mm,
            'usable_width_mm': USABLE_WIDTH / mm,
            'usable_height_mm': USABLE_HEIGHT / mm
        },
        'bubbles': [
            {
                'page': b.page,
                'x_mm': b.x,
                'y_mm': b.y,
                'field': b.field_name,
                'value': b.value
            }
            for b in metadata
        ]
    }

    with open(output_metadata, 'w') as f:
        json.dump(metadata_dict, f, indent=2)

    print(f"Generated: {output_pdf}, {output_metadata} | Sheet ID: {sheet_id} | Bubbles: {len(metadata)}")

    return sheet_id


def generate_answer_key_sheet(exam_config: Dict, answer_key: Dict, output_pdf: str,
                               output_metadata: str, sheet_id: str = None):
    """
    Generate OMR sheet with correct answers marked (filled bubbles).
    Useful for creating answer key reference sheets.

    IMPORTANT: Uses the exact same layout as generate_omr_sheet to ensure
    metadata coordinates match the rendered positions.

    exam_config: Same structure as generate_omr_sheet
    answer_key: Dictionary mapping question fields to correct answers
                {'Q1': {'correct': ['A']}, 'Q21': {'correct': ['1234']}, ...}
    output_pdf: Output PDF file path for marked answer key
    output_metadata: Output JSON metadata file path
    sheet_id: Unique identifier (auto-generated if not provided)
    """
    if sheet_id is None:
        sheet_id = f"ANSWER-KEY-{str(uuid.uuid4())[:8].upper()}"

    # Create blocks using the SAME shared function to ensure identical layout
    blocks = create_omr_blocks(exam_config)

    # Paginate blocks (same as regular OMR sheet)
    pages = paginate_blocks(blocks)

    # Generate metadata by rendering to a temporary in-memory metadata list
    metadata_list = []
    temp_pdf = output_pdf.replace('.pdf', '_temp.pdf')
    render_pages(pages, temp_pdf, metadata_list, sheet_id)

    # Save metadata to JSON
    metadata_dict = {
        'sheet_id': sheet_id,
        'total_pages': len(pages),
        'page_geometry': {
            'page_width_mm': PAGE_WIDTH / mm,
            'page_height_mm': PAGE_HEIGHT / mm,
            'usable_width_mm': USABLE_WIDTH / mm,
            'usable_height_mm': USABLE_HEIGHT / mm
        },
        'bubbles': [
            {
                'page': b.page,
                'x_mm': b.x,
                'y_mm': b.y,
                'field': b.field_name,
                'value': b.value
            }
            for b in metadata_list
        ]
    }

    with open(output_metadata, 'w') as f:
        json.dump(metadata_dict, f, indent=2)

    # Now render the answer key PDF with filled bubbles using the SAME pages
    c = canvas.Canvas(output_pdf, pagesize=A4)
    render_pages_with_answers(c, pages, metadata_dict, answer_key, sheet_id)

    # Clean up temporary file
    import os
    if os.path.exists(temp_pdf):
        os.remove(temp_pdf)

    print(f"Answer Key Sheet Generated: {output_pdf} | Sheet ID: {sheet_id}")
    return sheet_id


def render_pages_with_answers(c: canvas.Canvas, pages: List[List[Block]],
                               metadata: Dict, answer_key: Dict, sheet_id: str):
    """Render pages with correct answers marked (filled bubbles)"""

    barcode_img = generate_barcode(sheet_id)
    barcode_width = 60 * mm
    barcode_height = 12 * mm

    # Create set of bubbles to fill based on answer key
    bubbles_to_fill = set()

    for q_field, q_data in answer_key.items():
        correct_answers = q_data.get('correct', [])

        for ans in correct_answers:
            # Check if this is an integer answer (multi-digit)
            if len(ans) > 1 and ans.isdigit():
                # Mark individual digit bubbles
                for digit_pos, digit_val in enumerate(ans):
                    field_name = f"{q_field}_D{digit_pos}"
                    bubbles_to_fill.add((field_name, digit_val))
            else:
                # MCQ answer
                bubbles_to_fill.add((q_field, ans))

    metadata_list = []
    tracker = CoordinateTracker()

    for page_num, page_blocks in enumerate(pages, start=1):
        # Draw alignment boxes at four corners
        draw_alignment_boxes(c)

        # Center the barcode horizontally at the top
        barcode_x = (PAGE_WIDTH - barcode_width) / 2
        barcode_y = PAGE_HEIGHT - MARGIN_TOP + 2 * mm
        c.drawImage(barcode_img, barcode_x, barcode_y, width=barcode_width, height=barcode_height)

        for block in page_blocks:
            y_start = PAGE_HEIGHT - MARGIN_TOP - block.y_offset

            if DEBUG_DRAW_BLOCKS:
                c.setStrokeColorRGB(1, 0, 0)
                c.setLineWidth(0.5)
                c.rect(MARGIN_LEFT + block.x_offset, y_start - block.height, block.width, block.height)
                c.setStrokeColorRGB(0, 0, 0)
                c.setLineWidth(1)

            if block.block_type == 'header':
                render_header_block(c, block, y_start, page_num, metadata_list, tracker)
            elif block.block_type == 'response_header':
                render_response_header(c, block, y_start)
            elif block.block_type == 'section_header':
                render_section_header(c, block, y_start)
            elif block.block_type == 'subsection_header':
                render_subsection_header(c, block, y_start)
            elif block.block_type == 'instructions':
                render_instructions_box(c, block, y_start)
            elif block.block_type == 'signatures':
                render_signature_boxes(c, block, y_start)
            elif block.block_type == 'questions':
                render_question_block_with_answers(c, block, y_start, page_num,
                                                   metadata_list, bubbles_to_fill)

        c.showPage()

    c.save()


def render_question_block_with_answers(c: canvas.Canvas, block: Block, y_start: float,
                                       page_num: int, metadata: List[BubbleMetadata],
                                       bubbles_to_fill: set):
    """Render question blocks with correct answers filled"""
    questions = block.content['questions']
    cols = block.content['cols']
    question_height = block.content['question_height']

    for q_data in questions:
        row = q_data['row']
        col = q_data['col']

        col_width = block.width / cols
        x_base = MARGIN_LEFT + block.x_offset + col * col_width
        y_base = y_start - row * question_height

        if q_data['type'] == 'integer':
            num_digits = q_data['digits']
            digit_spacing = 4.5*mm

            # Draw question number (matching render_question_block)
            c.setFont("Helvetica-Bold", 7)
            c.drawString(x_base - 0.5*mm, y_base - 3.1*mm, f"Q{q_data['number']}")

            c.setFont("Helvetica", 6)
            for digit_pos in range(num_digits):
                for digit_val in range(10):
                    bubble_x = x_base + 8*mm + digit_pos * digit_spacing
                    bubble_y = y_base - 2.5*mm - digit_val * (2 * BUBBLE_RADIUS + BUBBLE_VERTICAL_SPACING)

                    # Check if this bubble should be filled
                    field_name = f"Q{q_data['number']}_D{digit_pos}"
                    should_fill = (field_name, str(digit_val)) in bubbles_to_fill

                    if should_fill:
                        # Draw filled bubble
                        c.setFillColorRGB(0, 0, 0)
                        c.circle(bubble_x, bubble_y, BUBBLE_RADIUS, stroke=1, fill=1)
                        c.setFillColorRGB(1, 1, 1)  # White text on black bubble
                        c.drawString(bubble_x - 0.7*mm, bubble_y - 0.7*mm, str(digit_val))
                        c.setFillColorRGB(0, 0, 0)
                    else:
                        draw_bubble(c, bubble_x, bubble_y)
                        c.setFillColorRGB(*BUBBLE_TEXT_COLOR)
                        c.drawString(bubble_x - 0.7*mm, bubble_y - 0.7*mm, str(digit_val))
                        c.setFillColorRGB(0, 0, 0)

                    metadata.append(BubbleMetadata(
                        page=page_num,
                        x=bubble_x / mm,
                        y=bubble_y / mm,
                        field_name=field_name,
                        value=str(digit_val)
                    ))
        else:
            options = q_data['options']
            bubble_spacing = 4.5*mm

            # Draw question number and bubbles (matching render_question_block)
            c.setFont("Helvetica-Bold", 7)
            bubble_y = y_base - 2.5*mm
            c.drawString(x_base - 0.5*mm, bubble_y - 0.6*mm, f"Q{q_data['number']}")

            c.setFont("Helvetica", 7)
            for i, option in enumerate(options):
                bubble_x = x_base + 8*mm + i * bubble_spacing

                # Check if this bubble should be filled
                should_fill = (f"Q{q_data['number']}", option) in bubbles_to_fill

                if should_fill:
                    # Draw filled bubble
                    c.setFillColorRGB(0, 0, 0)
                    c.circle(bubble_x, bubble_y, BUBBLE_RADIUS, stroke=1, fill=1)
                    c.setFillColorRGB(1, 1, 1)
                    c.drawString(bubble_x - 0.8*mm, bubble_y - 0.8*mm, option)
                    c.setFillColorRGB(0, 0, 0)
                else:
                    draw_bubble(c, bubble_x, bubble_y)
                    c.setFillColorRGB(*BUBBLE_TEXT_COLOR)
                    c.drawString(bubble_x - 0.8*mm, bubble_y - 0.8*mm, option)
                    c.setFillColorRGB(0, 0, 0)

                metadata.append(BubbleMetadata(
                    page=page_num,
                    x=bubble_x / mm,
                    y=bubble_y / mm,
                    field_name=f"Q{q_data['number']}",
                    value=option
                ))


if __name__ == '__main__':
    # Example exam configuration
    exam = {
        'candidate_fields': [
            {'name': 'Roll No', 'options': list(range(10)), 'type': 'digits','digits':8},
            {'name': 'Set', 'options': ['A', 'B', 'C', 'D'], 'type': 'options-only'},
            {'name': 'Center Code', 'options': list(range(10)), 'type': 'digits','digits':5},
            {'name': 'Roll No2', 'options': list(range(10)), 'type': 'digits','digits':8},
            {'name': 'Set2', 'options': ['A', 'B', 'C', 'D'], 'type': 'options-only'},
            {'name': 'Center Code2', 'options': list(range(10)), 'type': 'digits','digits':5}
        ],
        'sections': [
            {
                'name': 'PHYSICS',
                'question_groups': [
                    {
                        'type': 'mcq',
                        'questions': [
                            {'number': i, 'options': ['A', 'B', 'C', 'D']}
                            for i in range(1, 37)
                        ]
                    },
                    {
                        'type': 'integer',
                        'questions': [
                            {'number': i, 'type': 'digits', 'digits': 5}
                            for i in range(38, 79)
                        ]
                    }
                ]
            },
            {
                'name': 'CHEMISTRY',
                'question_groups': [
                    {
                        'type': 'mcq',
                        'questions': [
                            {'number': i, 'options': ['A', 'B', 'C', 'D','E']}
                            for i in range(80, 82)
                        ]
                    }
                ]
            },
            {
                'name': 'MATHEMATICS',
                'question_groups': [
                    {
                        'type': 'mcq',
                        'questions': [
                            {'number': i, 'options': ['A', 'B', 'C', 'D','E','F']}
                            for i in range(83, 96)
                        ]
                    },
                    {
                        'type': 'integer',
                        'questions': [
                            {'number': i, 'type': 'digits', 'digits': 6}
                            for i in range(97, 111)
                        ]
                    }
                ]
            }
        ]
    }

    generate_omr_sheet(exam, 'omr_sheet.pdf', 'omr_layout.json')
    with open('answer_key.json', 'r') as f:
        answer_key = json.load(f)
    generate_answer_key_sheet(exam, answer_key, 'answer_key_sheet.pdf', 'answer_key_layout.json')