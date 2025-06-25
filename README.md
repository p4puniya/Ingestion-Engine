# Ingestion Engine

A simple tool to extract and process content from URLs and PDFs.
Please note, when ingesting large amounts of data like Entire Books, The Process can appear as stuck but it is not. Check the terminal where you are running the backend for live progress. 

Also, I suggest using the frontend :)

## Quick Start
0. **[Optional] Update the .env & Create a venv**
   ```
   1. python -m venv .myenv
   2. .myenv\Scripts\activate
   3. add the OPENAI API KEY to fetch authors more accurately.
   ```
1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Start the backend:**
   ```bash
   uvicorn app:app --reload
   ```

3. **Start the frontend:**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

4. **Open in browser:**
   - Frontend: http://localhost:5173
   - Backend: http://localhost:8000

## Usage

1. **Upload PDFs** or **enter URLs** (one per line)
2. **Set Team ID** (required)
3. **Choose Author Mode:**
   - Cost Saving: 200 chars, $0.001
   - Balanced: 500 chars, $0.002  
   - Accuracy: 1000 chars, $0.004
4. **Click "Process Content"**
5. **Download results** as JSON or Markdown

## Features

- ✅ Extract text from PDFs
- ✅ Scrape content from URLs
- ✅ Auto-detect authors using OpenAI
- ✅ Generate structured JSON output
- ✅ Export to Markdown format
- ✅ Batch processing support

## API Endpoints

- `POST /ingest/batch` - Process multiple files/URLs
- `POST /ingest/pdf-upload` - Upload single PDF
- `POST /ingest/url` - Process single URL

## Requirements

- Python 3.8+
- Node.js 16+
- OpenAI API key (optional, for author detection)
