"""
Prompt Templates for the Extraction Pipeline

Specialized, type-aware prompts that dramatically improve extraction quality
over a single generic prompt.
"""


# ──────────────────────────────────────────────
# Stage 2: Structure Analysis Prompt
# ──────────────────────────────────────────────

STRUCTURE_ANALYSIS_PROMPT = """You are a document structure analysis expert. Analyze this exam/question paper and return a detailed blueprint.

## YOUR TASK
Analyze the document below and extract its EXACT structure. Do NOT extract the questions themselves — only identify HOW the document is organized.

## WHAT TO DETECT

1. **Document Type**: Is this a question paper, answer key, syllabus, or other?
2. **Subjects**: What subjects are present? (e.g., Physics, Chemistry, Mathematics)
3. **Sections per Subject**: For each subject, what sections exist?
   - Section name (e.g., "Section A", "Part I", "MCQ Section")
   - Question type in that section (single_mcq, multiple_mcq, numerical, subjective, true_false, fill_blank)
   - Question number range (e.g., Q1-Q20)
   - Marks per question
   - Negative marking (if any)
4. **Instructions**: Any general instructions or marking scheme at the top
5. **Question Numbering**: How are questions numbered? (Q1., 1., (1), etc.)
6. **Answer Format**: How are answers shown? (Answer: A, Ans: B, etc.)

## PATTERN CONTEXT
This document should match a pattern with these subjects: {pattern_subjects}
Expected total questions: {expected_total}

## OUTPUT FORMAT
Return ONLY this JSON (no other text):
```json
{{
    "document_type": "questions_with_answers",
    "confidence": 0.95,
    "instructions": "General instructions text here...",
    "subjects": [
        {{
            "name": "Physics",
            "start_position": "beginning of Physics section marker text...",
            "sections": [
                {{
                    "name": "Section A - Single Correct MCQ",
                    "question_type": "single_mcq",
                    "start_question": 1,
                    "end_question": 20,
                    "question_count": 20,
                    "marks_per_question": 4,
                    "negative_marking": -1,
                    "format_description": "4 options A-D, one correct answer"
                }},
                {{
                    "name": "Section B - Numerical",
                    "question_type": "numerical",
                    "start_question": 21,
                    "end_question": 25,
                    "question_count": 5,
                    "marks_per_question": 4,
                    "negative_marking": 0,
                    "format_description": "Answer is a number, no options"
                }}
            ]
        }}
    ],
    "total_questions": 75,
    "numbering_format": "Q1.",
    "answer_format": "Answer: A",
    "validation": {{
        "matches_pattern": true,
        "issues": [],
        "subject_match_score": 1.0
    }}
}}
```

## IMPORTANT RULES
1. Be PRECISE about question number ranges — count carefully
2. Match subjects to the provided pattern subjects
3. If subjects restart numbering (e.g., Physics Q1-25, Chemistry Q1-25), note this
4. Detect ALL sections, even small ones (e.g., 5 numerical questions)

## DOCUMENT TEXT (first 15000 chars):
{document_text}
"""


# ──────────────────────────────────────────────
# Stage 4: Type-Specific Extraction Prompts
# ──────────────────────────────────────────────

MCQ_EXTRACTION_PROMPT = """You are a question extraction expert specializing in Multiple Choice Questions.

## TASK
Extract ALL MCQ questions from this text chunk. This chunk contains approximately {expected_count} questions from the "{section_name}" section of "{subject}".

## QUESTION TYPE
- **{question_type}**: {type_description}

## MCQ STRUCTURE
Each MCQ has:
1. Question text (may include LaTeX, images, tables)
2. 4-5 options labeled (A), (B), (C), (D), or A), B), C), D) or 1), 2), 3), 4)
3. Correct answer(s)
4. Optional: Solution/explanation

## CRITICAL: SINGLE vs MULTIPLE CORRECT ANSWERS
- **single_mcq**: The question has EXACTLY ONE correct answer. Return just one letter: "B"
- **multiple_mcq**: The question has ONE OR MORE correct answers. Return comma-separated letters: "A,C" or "B,C,D"
  - Look for keywords: "one or more correct", "select all that apply", "which of the following", "correct statement(s)"
  - If ALL options could be correct, return "A,B,C,D"
  - The answer format for multiple_mcq is ALWAYS comma-separated: "A,C" not "AC"

## LaTeX PRESERVATION
- Keep ALL LaTeX exactly as-is: $\\frac{{1}}{{2}}$, $\\sqrt{{x}}$, $\\int_0^1$
- Do NOT simplify, convert, or remove LaTeX
- Preserve $$...$$ for display math and $...$ for inline math

## OUTPUT FORMAT
Return ONLY a JSON array:
```json
[
    {{
        "question_number": {start_q},
        "question_text": "Full question text with LaTeX preserved",
        "question_type": "{question_type}",
        "options": ["Option A text", "Option B text", "Option C text", "Option D text"],
        "correct_answer": "B",
        "solution": "Solution explanation here",
        "difficulty": "medium",
        "has_latex": false
    }}
]
```

## EXAMPLES BY TYPE

### Single Correct (single_mcq):
```json
{{
    "question_type": "single_mcq",
    "correct_answer": "C"
}}
```

### Multiple Correct (multiple_mcq):
```json
{{
    "question_type": "multiple_mcq",
    "correct_answer": "A,C,D"
}}
```

## RULES
1. Extract EVERY question — do not skip any
2. question_number: Use the ORIGINAL numbering from the document
3. options: Array of option texts WITHOUT the letter prefix (A/B/C/D)
4. correct_answer: For single_mcq → "B". For multiple_mcq → "A,C" (comma-separated)
5. If answer is not clearly marked, set correct_answer to "" and note in solution
6. Preserve ALL formatting and LaTeX
7. If you detect that a question marked as single_mcq actually has multiple correct answers, set question_type to "multiple_mcq"

## TEXT TO EXTRACT FROM:
{chunk_text}

## JSON OUTPUT:"""


NUMERICAL_EXTRACTION_PROMPT = """You are a question extraction expert specializing in Numerical/Integer questions.

## TASK
Extract ALL numerical questions from this text chunk. This chunk contains approximately {expected_count} questions from the "{section_name}" section of "{subject}".

## NUMERICAL QUESTION STRUCTURE
Each question has:
1. Question text (often with calculations, formulas, LaTeX)
2. NO options (or sometimes range hints)
3. Answer: A numeric value (integer or decimal)
4. Optional: Tolerance, units, solution

## LaTeX PRESERVATION
- Keep ALL LaTeX exactly as-is
- Mathematical expressions are crucial in numerical questions
- Preserve fractions, integrals, summations, etc.

## OUTPUT FORMAT
Return ONLY a JSON array:
```json
[
    {{
        "question_number": {start_q},
        "question_text": "Full question text with LaTeX preserved",
        "question_type": "numerical",
        "options": [],
        "correct_answer": "42.5",
        "solution": "Step by step solution here",
        "difficulty": "medium",
        "has_latex": true,
        "tolerance": 0.01
    }}
]
```

## RULES
1. Extract EVERY question — count carefully
2. correct_answer: The numeric value as a STRING (e.g., "42", "3.14", "-5")
3. If answer shows a range (e.g., 42 ± 0.5), include tolerance field
4. Preserve ALL LaTeX in question_text
5. Include step-by-step solution if available

## TEXT TO EXTRACT FROM:
{chunk_text}

## JSON OUTPUT:"""


SUBJECTIVE_EXTRACTION_PROMPT = """You are a question extraction expert specializing in Subjective/Essay questions.

## TASK
Extract ALL subjective questions from this text chunk. This chunk contains approximately {expected_count} questions from the "{section_name}" section of "{subject}".

## IMPORTANT: DETECT NESTED STRUCTURES
Subjective questions often have:
1. **Sub-parts**: (a), (b), (c) or (i), (ii), (iii)
2. **Internal Choices**: "OR" options (e.g., "Answer (a) OR (b)")

## OUTPUT FORMAT
Return ONLY a JSON array. Structure sub-parts in the `parts` array:
```json
[
    {{
        "question_number": {start_q},
        "question_text": "Main question text (e.g. 'Answer the following:')",
        "question_type": "subjective",
        "options": [],
        "correct_answer": "Model answer for main question if applicable",
        "solution": "Main solution/marking scheme",
        "difficulty": "hard",
        "has_latex": false,
        "parts": [
            {{
                "label": "a",
                "text": "Calculate the velocity...",
                "marks": 3,
                "solution": "v = u + at..."
            }},
            {{
                "label": "b",
                "text": "Derive the equation...",
                "marks": 5,
                "solution": "Start with F=ma..."
            }}
        ],
        "is_nested": true
    }}
]
```

## RULES
1. **Always Extract Sub-parts**: If a question has (a), (b), (c), put them in the `parts` array. Do NOT just mash them into `question_text`.
2. **Internal Choices**: If two questions are separated by "OR", extraction depends on numbering:
   - If they have SAME number (Q5 ... OR ...), extract as ONE question with `internal_choice` format (describe in text or as parts).
   - If "OR" is between parts (a) OR (b), treat as parts.
3. **Marks**: Extract marks per part if visible (e.g., "[3 marks]").
4. **Latex**: Preserve ALL LaTeX exactly.

## TEXT TO EXTRACT FROM:
{chunk_text}

## JSON OUTPUT:"""


# ──────────────────────────────────────────────
# True/False Extraction Prompt  
# ──────────────────────────────────────────────

TRUE_FALSE_EXTRACTION_PROMPT = """You are a question extraction expert specializing in True/False questions.

## TASK
Extract ALL True/False questions from this text chunk. This chunk contains approximately {expected_count} questions from the "{section_name}" section of "{subject}".

## TRUE/FALSE QUESTION STRUCTURE
Each question has:
1. A statement that is either TRUE or FALSE
2. The correct answer: "True" or "False" (or T/F)
3. Optional: Explanation of why the statement is true or false

## HOW TO IDENTIFY TRUE/FALSE QUESTIONS
- Look for: "True or False", "T/F", "State whether true or false", "Mark true or false"
- Each question is a factual STATEMENT (not a question with "?") followed by True/False evaluation
- Sometimes formatted as: "Statement... (True/False)"
- Sometimes listed as assertions that must be judged as correct or incorrect

## OUTPUT FORMAT
Return ONLY a JSON array:
```json
[
    {{
        "question_number": {start_q},
        "question_text": "The statement to be judged as True or False",
        "question_type": "true_false",
        "options": ["True", "False"],
        "correct_answer": "True",
        "solution": "Explanation of why this is true/false",
        "difficulty": "easy",
        "has_latex": false
    }}
]
```

## RULES
1. Extract EVERY True/False question
2. question_type must be "true_false" for all questions
3. options should always be ["True", "False"]
4. correct_answer should be exactly "True" or "False" (capitalized)
5. If a statement is actually an assertion-reason type, still classify as true_false
6. Preserve ALL LaTeX and formatting
7. Use original question numbers from the document

## TEXT TO EXTRACT FROM:
{chunk_text}

## JSON OUTPUT:"""


# ──────────────────────────────────────────────
# Fill in the Blanks Extraction Prompt
# ──────────────────────────────────────────────

FILL_BLANK_EXTRACTION_PROMPT = """You are a question extraction expert specializing in Fill-in-the-Blank questions.

## TASK
Extract ALL fill-in-the-blank questions from this text chunk. This chunk contains approximately {expected_count} questions from the "{section_name}" section of "{subject}".

## FILL-IN-THE-BLANK STRUCTURE
Each question has:
1. A sentence or passage with one or more blanks (shown as ___, ______, [blank], <blank>, or ........)
2. The correct word(s) or phrase(s) to fill in each blank
3. Optional: Multiple blanks in one question
4. Blanks may sometimes have options provided (making them more like MCQs, but classify as fill_blank)

## HOW TO IDENTIFY FILL-IN-THE-BLANK QUESTIONS
- Look for: underscores (___), dots (....), dashes (----), [blank], "fill in"
- Sentences with missing words: "The ____ is the powerhouse of the cell"
- Sometimes formatted with numbered blanks: "(i) ___ (ii) ___"
- Sometimes with a word bank provided

## OUTPUT FORMAT
Return ONLY a JSON array:
```json
[
    {{
        "question_number": {start_q},
        "question_text": "The _____ is the powerhouse of the cell.",
        "question_type": "fill_blank",
        "options": [],
        "correct_answer": "mitochondria",
        "solution": "The mitochondria generates most of the cell's ATP",
        "difficulty": "easy",
        "has_latex": false,
        "blanks_count": 1
    }}
]
```

## RULES FOR MULTIPLE BLANKS
- If a question has multiple blanks, list all answers comma-separated in correct_answer
  Example: correct_answer = "mitochondria, nucleus, ribosome"
- Set blanks_count to the number of blanks in the question
- Preserve the original blank markers (___) in question_text

## RULES
1. Extract EVERY fill-in-the-blank question
2. question_type must be "fill_blank" for all questions
3. If options/word bank are provided, include them in the options array
4. correct_answer should have the exact word(s) that fill the blank(s)
5. Preserve ALL LaTeX and formatting
6. Keep the blank markers in the question text
7. Use original question numbers from the document

## TEXT TO EXTRACT FROM:
{chunk_text}

## JSON OUTPUT:"""


# ──────────────────────────────────────────────
# Generic prompt for mixed/unknown sections
# ──────────────────────────────────────────────

GENERIC_EXTRACTION_PROMPT = """You are a question extraction expert. Extract ALL questions from this text chunk.

## TASK
Extract approximately {expected_count} questions from the "{section_name}" section of "{subject}".

## IMPORTANT: DETECT QUESTION TYPE ACCURATELY
You MUST classify each question into one of these types:

| Type | How to Identify | correct_answer Format |
|------|-----------------|----------------------|
| **single_mcq** | 4 options, ONE correct answer | "B" |
| **multiple_mcq** | 4 options, MULTIPLE correct answers. Keywords: "one or more", "all that apply", "correct statement(s)" | "A,C,D" (comma-separated) |
| **numerical** | Answer is a number, no options | "42.5" |
| **true_false** | Statement to judge True/False. Keywords: "true or false", "T/F" | "True" or "False" |
| **fill_blank** | Has blanks ___ to fill in | "answer word" |
| **subjective** | Requires written explanation. Keywords: "explain", "describe", "derive" | Key points as text |

## LaTeX PRESERVATION
- Keep all LaTeX exactly as-is

## OUTPUT FORMAT
Return ONLY a JSON array:
```json
[
    {{
        "question_number": 1,
        "question_text": "Full question text",
        "question_type": "single_mcq",
        "options": ["Option A", "Option B", "Option C", "Option D"],
        "correct_answer": "C",
        "solution": "Solution here",
        "difficulty": "medium",
        "has_latex": false
    }}
]
```

## TYPE-SPECIFIC RULES
- **single_mcq / multiple_mcq**: options = ["text", "text", ...], correct_answer = letter(s)
- **true_false**: options = ["True", "False"], correct_answer = "True" or "False"
- **fill_blank**: options = [] (or word bank if given), correct_answer = the word/phrase
- **numerical**: options = [], correct_answer = numeric string
- **subjective**: options = [], correct_answer = model answer text

## RULES
1. Extract EVERY question — do not skip any
2. Classify question_type accurately based on the structure above
3. Preserve all LaTeX and formatting
4. Use original question numbers from the document
5. Options array should be empty [] for non-MCQ/non-true_false questions

## TEXT TO EXTRACT FROM:
{chunk_text}

## JSON OUTPUT:"""


# ──────────────────────────────────────────────
# Stage 5: Validation Prompt
# ──────────────────────────────────────────────

VALIDATION_RETRY_PROMPT = """You are a question extraction validator. The previous extraction MISSED some questions. 

## CONTEXT
- Expected {expected_count} questions in this section
- Only {extracted_count} were extracted
- Missing approximately {missing_count} questions

## MISSING QUESTIONS
Look carefully for questions that were missed. They might be:
- Questions formatted differently (tables, nested, merged with solutions)
- Questions at the boundary between sections
- Questions with unusual numbering

## SECTION INFO
Subject: {subject}
Section: {section_name}
Type: {question_type}
Question Range: Q{start_q} to Q{end_q}

## ALREADY EXTRACTED NUMBERS
{extracted_numbers}

## TEXT TO RE-EXAMINE:
{chunk_text}

## TASK
Find and extract ONLY the MISSING questions (those not in the "already extracted" list).
Return them in the same JSON format:
```json
[
    {{
        "question_number": 1,
        "question_text": "...",
        "question_type": "{question_type}",
        "options": [],
        "correct_answer": "...",
        "solution": "...",
        "difficulty": "medium",
        "has_latex": false
    }}
]
```

## JSON OUTPUT (missing questions only):"""
