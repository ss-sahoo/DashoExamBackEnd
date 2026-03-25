# ExamFlow Extraction Service

## Overview
This is a dedicated microservice for extracting questions from PDFs using AI and OCR.
It uses FastAPI and LangGraph to manage the extraction pipeline.

## Structure
```
extraction_service/
├── main.py             # FastAPI entry point
├── requirements.txt    # Dependencies
├── core/
│   ├── config.py       # Settings
│   ├── graph.py        # LangGraph definition
│   ├── nodes.py        # Pipeline steps
│   ├── state.py        # Data models
│   └── services/
│       ├── gemini.py   # AI extraction (Google Gemini)
│       ├── mathpix.py  # OCR (Mathpix)
│       └── chunker.py  # Document splitting
```

## Running Locally

1. Install dependencies:
   ```bash
   cd extraction_service
   pip install -r requirements.txt
   ```

2. Set environment variables:
   ```bash
   export GEMINI_API_KEY="your_key"
   export MATHPIX_APP_ID="your_id"
   export MATHPIX_APP_KEY="your_key"
   ```

3. Run the service:
   ```bash
   uvicorn main:app --reload --port 8020
   ```

## API Endpoints

- `POST /extract`: Submit a file for extraction.
  ```json
  {
    "file_path": "/absolute/path/to/file.pdf",
    "pattern_id": "optional_pattern_id",
     "expected_count": 50
  }
  ```
  Returns: `{"job_id": "uuid", "status": "processing"}`

- `GET /jobs/{job_id}`: Check status.
  Returns: `{"status": "completed", "result": {...}}`
