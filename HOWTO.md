# HOWTO: Knowledge Ingestion Engine

This guide explains all major features of the project, how to use them, and how to test them. It covers CLI, API, frontend, ingestion, chunking, metadata, auto-tagging, supported sources, output format, Docker, and the test suite.

---

## 1. Overview

The Knowledge Ingestion Engine ingests technical knowledge from blogs, guides, Substack, Quill, and PDFs, chunks it intelligently, extracts metadata, auto-tags content, and outputs everything in a standardized JSON format for LLM-ready knowledgebases.

---

## 2. Features & Functions

### 2.1. Ingestion (Extraction)
- **Supported sources:**
  - Any blog (robust extraction, no custom code per source)
  - Guides (e.g., interviewing.io topics)
  - Substack blogs
  - Quill blogs
  - PDFs (including heading-based chunking)
- **How it works:**
  - Extracts main content, title, author, and metadata.
  - Converts HTML to markdown.
  - For PDFs, extracts text and detects headings by font size/caps.

### 2.2. Chunking
- **Intelligent chunking:**
  - Splits markdown by headings (fallback: paragraphs).
  - Splits PDFs by detected headings.
- **Why:**
  - Makes content LLM-friendly and easy to search.

### 2.3. Metadata Extraction
- **Extracts:**
  - Title, author, date, tags, word count, reading time, OpenGraph/JSON-LD metadata.

### 2.4. Auto-Tagging
- **How:**
  - Uses spaCy (noun chunks/entities) or TF-IDF to generate tags for each chunk.

### 2.5. Output Format
- **Standardized JSON:**
  ```json
  {
    "team_id": "aline123",
    "items": [
      {
        "title": "Item Title",
        "content": "Markdown content",
        "content_type": "blog|book|other",
        "source_url": "optional-url",
        "author": "",
        "user_id": ""
      }
    ]
  }
  ```
- **All output is markdown.**

---

## 3. How to Use

### 3.1. CLI
- **Ingest from a URL:**
  ```bash
  ingestai ingest-url <URL> --team-id aline123 [--user-id <user>]
  ```
- **Ingest from a PDF:**
  ```bash
  ingestai ingest-pdf <path/to/your.pdf> --team-id aline123 [--user-id <user>]
  ```
- **Output:**
  - JSON file in `output/` directory.
  - Follows the required format.

### 3.2. API
- **Start the server:**
  ```bash
  uvicorn app:app --reload
  ```
- **Ingest from a URL:**
  ```http
  POST /ingest/url
  {
    "url": "https://interviewing.io/blog",
    "team_id": "aline123",
    "user_id": "optional"
  }
  ```
- **Ingest from a PDF file path:**
  ```http
  POST /ingest/pdf
  {
    "filepath": "path/to/your.pdf",
    "team_id": "aline123",
    "user_id": "optional"
  }
  ```
- **Ingest from a PDF upload (for frontend):**
  ```http
  POST /ingest/pdf-upload
  FormData: file=<PDF>, team_id=aline123, user_id=optional
  ```
- **Async ingestion with webhook:**
  ```http
  POST /ingest/url/async
  {
    "url": "...",
    "webhook_url": "..."
  }
  ```
- **Response:**
  - JSON in the required format.

### 3.3. Frontend
- **Start frontend:**
  ```bash
  cd frontend
  npm start
  ```
- **Features:**
  - Enter a URL or upload a PDF.
  - Enter team_id and user_id.
  - See output JSON preview and download.
  - Handles errors and loading states.
- **Backend:**
  - Make sure FastAPI is running at `http://localhost:8000` (or set `REACT_APP_API_URL`).

### 3.4. Docker
- **Build and run:**
  ```bash
  docker build -t ingestai .
  docker run -p 8000:8000 ingestai
  ```
- **API available at:**
  - `http://localhost:8000`

---

## 4. How to Test

### 4.1. Run the test suite
- **Command:**
  ```bash
  pytest tests/test_sources.py
  ```
- **What it tests:**
  - Ingestion and chunking for all required sources:
    - interviewing.io blog
    - company guides
    - interview guides
    - Nil's DSA blog
    - Quill blog
    - Substack
    - Wikipedia (stability)
    - PDF (add your sample at `tests/sample_book.pdf`)
  - Output format compliance
  - Metadata and chunk structure

### 4.2. Manual Testing
- **Try the CLI, API, and frontend with any blog, guide, Substack, or PDF.**
- **Check the output JSON for correct fields and markdown content.**

---

## 5. Advanced/Developer Notes

- **Add new extractors or chunkers** in `scraper/` as needed.
- **All output is markdown and LLM-ready.**
- **No custom code per source is needed.**
- **Auto-tagging and metadata are extensible.**

---

For any questions, see the README or open an issue. 