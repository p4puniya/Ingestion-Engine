import click
from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from scraper.extract import extract_from_url, extract_from_pdf
from scraper.chunker import chunk_document, generate_ingestion_payload, generate_raw_payload
import json
import uuid
import os
import requests
from scraper.utils import build_output
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import tempfile
from scraper.discovery import discover_content_from_url
from dotenv import load_dotenv
import asyncio
import time

# Load environment variables from .env file
load_dotenv()

# Debug: Check if OpenAI API key is loaded
openai_key = os.getenv('OPENAI_API_KEY')
print(f"[DEBUG] OPENAI_API_KEY loaded: {'Yes' if openai_key else 'No'}")
if openai_key:
    print(f"[DEBUG] OpenAI API key starts with: {openai_key[:8]}...")
else:
    print("[DEBUG] No OpenAI API key found in environment variables")

app = FastAPI(
    title="Ingestion Engine",
    description="A service to ingest and process content from various sources.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For dev, allow all. For prod, restrict to your frontend URL.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def process_and_save(document: dict, source_identifier: str, team_id: str, content_type: str, user_id: str = "default_user", chunked: bool = False):
    """Helper function to chunk a document and save it to a file."""
    # Always use the chunking logic to ensure metadata (including author) is preserved
    processed_output = generate_ingestion_payload(document, team_id=team_id, user_id=user_id)
    items = processed_output["items"]
    if not items:
        return None
    output = {
        "team_id": team_id,
        "items": items
    }
    if not os.path.exists("output"):
        os.makedirs("output")
    output_filename = f"output/{str(uuid.uuid4())}.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    return {"source": source_identifier, "chunk_count": len(items), "output_file": output_filename, "output": output}

@app.get("/")
def read_root():
    """A welcome message."""
    return {"message": "Welcome to the Ingestion Engine API"}

class IngestUrlRequest(BaseModel):
    url: str
    team_id: str
    user_id: str = ""
    depth: int = 0
    exclude_urls: Optional[List[str]] = None

def crawl_urls(start_url, depth, visited=None, exclude_urls=None):
    if visited is None:
        visited = set()
    if exclude_urls is None:
        exclude_urls = set()
    else:
        exclude_urls = set(exclude_urls)
    if depth < 0 or start_url in visited or start_url in exclude_urls:
        return []
    visited.add(start_url)
    try:
        resp = requests.get(start_url, timeout=15)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"[crawl_urls] Failed to fetch {start_url}: {e}")
        return []
    soup = BeautifulSoup(html, "html.parser")
    found_urls = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        abs_url = urljoin(start_url, href)
        # Only crawl same domain or http(s) links
        if urlparse(abs_url).scheme in ("http", "https"):
            if abs_url not in exclude_urls:
                found_urls.add(abs_url)
    # --- NEW: Use discovery module to find more URLs ---
    discovery_results = discover_content_from_url(start_url, max_depth=depth)
    # Merge discovered URLs (content, pagination, category)
    extra_urls = set()
    extra_urls.update(discovery_results.get('content_urls', set()))
    extra_urls.update(discovery_results.get('pagination_urls', set()))
    extra_urls.update(discovery_results.get('category_urls', set()))
    # Remove already visited and excluded
    extra_urls = {u for u in extra_urls if u not in visited and u not in exclude_urls}
    found_urls.update(extra_urls)
    # --- END NEW ---
    results = [(start_url, html, found_urls)]
    if depth > 0:
        for url in found_urls:
            results.extend(crawl_urls(url, depth-1, visited, exclude_urls))
    return results

@app.post("/ingest/url")
def ingest_url(request: IngestUrlRequest):
    # Crawl URLs up to the specified depth
    url_html_pairs = crawl_urls(request.url, request.depth, exclude_urls=request.exclude_urls)
    all_items = []
    all_urls = []
    all_raw_data = []
    
    # Track depth for each URL
    depth_map = {}
    depth_map[request.url] = 0
    
    for url, html, found_urls in url_html_pairs:
        # Calculate depth for this URL
        current_depth = depth_map.get(url, 0)
        
        # Add URLs found on this page
        all_urls.append({
            "original_url": url,
            "depth_level": current_depth,
            "found_urls": list(found_urls)
        })
        
        # Update depth for found URLs
        if current_depth < request.depth:
            for found_url in found_urls:
                if found_url not in depth_map:
                    depth_map[found_url] = current_depth + 1
        
        # Use the extraction logic, but pass the HTML directly
        document = extract_from_url(url, html_content=html)
        if document:
            # Generate processed output
            processed_output = generate_ingestion_payload(document, team_id=request.team_id, user_id=request.user_id)
            all_items.extend(processed_output["items"])
            
            # Generate raw output
            raw_output = generate_raw_payload(document, team_id=request.team_id, user_id=request.user_id)
            all_raw_data.append(raw_output)
    
    if all_items:
        processed_output = {"team_id": request.team_id, "items": all_items}
        raw_output = {"team_id": request.team_id, "raw_data": all_raw_data}
        
        return {
            "status": "success", 
            "processed_output": processed_output, 
            "raw_output": raw_output,
            "urls": all_urls
        }
    return {"status": "error", "url": request.url, "message": "Failed to extract content."}

@app.post("/ingest/pdf")
def ingest_pdf(filepath: str, team_id: str, user_id: str = "", source_url: str = None):
    document = extract_from_pdf(filepath, source_url=source_url)
    if document:
        result = process_and_save(document, filepath, team_id, content_type="book", user_id=user_id, chunked=True)
        return {"status": "success", **result}
    return {"status": "error", "filepath": filepath, "message": "Failed to extract content."}

@app.post("/ingest/pdf-upload")
def ingest_pdf_upload(
    file: UploadFile = File(...), 
    team_id: str = Form(...), 
    user_id: str = Form(""), 
    source_url: str = Form(None),
    author_mode: str = Form("balanced")
):
    import tempfile
    processing_log = []
    
    # Generate a unique task ID for this upload
    task_id = str(uuid.uuid4())
    
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(file.file.read())
            tmp_path = tmp.name
        
        extraction_msg = "📊 Extracting text from PDF... (this may take a few seconds)"
        
        # Use original filename as source_url if no custom source_url provided
        original_filename = file.filename
        effective_source_url = source_url or original_filename
        
        document = extract_from_pdf(tmp_path, source_url=effective_source_url, author_mode=author_mode)
        
        if document:
            chunk_msg = "📝 Generating chunks and metadata..."
            
            # Use original filename instead of temporary file path
            result = process_and_save(document, original_filename, team_id, content_type="book", user_id=user_id, chunked=True)
            
            completion_msg = f"✅ Processing complete! {result['chunk_count']} chunks created"
            
            os.remove(tmp_path)
            return {
                "task_id": task_id,
                "status": "success", 
                **result,
                "processing_log": processing_log
            }
        
        error_msg = "❌ Failed to extract content from PDF"
        os.remove(tmp_path)
        return {
            "task_id": task_id,
            "status": "error", 
            "message": "Failed to extract content from PDF.",
            "processing_log": processing_log
        }
        
    except Exception as e:
        error_msg = f"❌ Processing failed with error: {str(e)}"
        if 'tmp_path' in locals():
            try:
                os.remove(tmp_path)
            except:
                pass
        return {
            "task_id": task_id,
            "status": "error", 
            "message": str(e),
            "processing_log": processing_log
        }

def send_webhook(url: str, data: dict):
    """Sends a POST request to the specified webhook URL."""
    try:
        requests.post(url, json=data, timeout=10)
    except requests.RequestException as e:
        print(f"Failed to send webhook to {url}: {e}")

def process_url_in_background(url: str, webhook_url: str):
    """Background task for URL ingestion and webhook notification."""
    document = extract_from_url(url)
    if document:
        result = process_and_save(document, url, "", "", "")
        if webhook_url:
            send_webhook(webhook_url, {"status": "success", **result})
    else:
        if webhook_url:
            send_webhook(webhook_url, {"status": "error", "url": url, "message": "Failed to extract content."})

@app.post("/ingest/url/async")
def ingest_url_async(url: str, webhook_url: str, background_tasks: BackgroundTasks):
    """Ingests content from a URL asynchronously and sends a webhook upon completion."""
    background_tasks.add_task(process_url_in_background, url, webhook_url)
    return {"status": "processing", "message": "Ingestion started. A webhook will be sent upon completion."}

@app.post("/ingest/batch")
async def ingest_batch(
    request: Request,
    urls: List[str] = Form([]),
    pdfs: List[UploadFile] = File([]),
    team_id: str = Form(...),
    user_id: str = Form(""),
    author_mode: str = Form("balanced")
):
    all_items = []
    all_urls = []  # Collect URLs info for output
    
    # Process URLs with crawling/discovery
    for i, url in enumerate(urls, 1):
        # Use the same crawl_urls logic as /ingest/url, but only depth 0 for batch
        url_html_pairs = crawl_urls(url, 0)
        for url_entry, html, found_urls in url_html_pairs:
            all_urls.append({
                "original_url": url_entry,
                "depth_level": 0,
                "found_urls": list(found_urls)
            })
            document = extract_from_url(url_entry, html_content=html)
            if document and document.get("items"):
                all_items.extend(document["items"])
            elif document:
                # Fallback: try process_and_save logic
                result = process_and_save(document, url_entry, team_id, content_type="blog", user_id=user_id, chunked=True)
                if result and result.get("output") and result["output"].get("items"):
                    all_items.extend(result["output"]["items"])
    
    # Process PDFs
    for i, pdf_file in enumerate(pdfs, 1):
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(await pdf_file.read())
                tmp_path = tmp.name
            
            # Use original filename as source_url
            original_filename = pdf_file.filename
            
            document = extract_from_pdf(tmp_path, source_url=original_filename, author_mode=author_mode)
            
            if document and document.get("items"):
                all_items.extend(document["items"])
            elif document:
                # Fallback: try process_and_save logic
                # Use original filename instead of temporary file path
                result = process_and_save(document, original_filename, team_id, content_type="book", user_id=user_id, chunked=True)
                if result and result.get("output") and result["output"].get("items"):
                    all_items.extend(result["output"]["items"])
            
            os.remove(tmp_path)
            
        except Exception as e:
            if 'tmp_path' in locals():
                try:
                    os.remove(tmp_path)
                except:
                    pass
    
    # Remove author_method from all_items if present
    for item in all_items:
        if 'author_method' in item:
            del item['author_method']
    
    return {
        "team_id": team_id,
        "items": all_items,
        "urls": all_urls  # Add URLs info to output
    }

@click.group()
def cli():
    """A CLI for the Ingestion Engine."""
    pass

@cli.command("ingest-url")
@click.argument("url")
@click.option("--team-id", required=True, help="Team ID for output JSON.")
@click.option("--user-id", default="", help="User ID for output JSON.")
def ingest_url_command(url: str, team_id: str, user_id: str):
    """Ingests content from a given URL."""
    print(f"Ingesting from {url}...")
    document = extract_from_url(url)
    if document:
        result = process_and_save(document, url, team_id, content_type="blog", user_id=user_id)
        print(f"Successfully created {result['chunk_count']} chunks.")
        print(f"Output saved to {result['output_file']}")
    else:
        print("Failed to extract content.")

@cli.command("ingest-pdf")
@click.argument("filepath")
@click.option("--team-id", required=True, help="Team ID for output JSON.")
@click.option("--user-id", default="", help="User ID for output JSON.")
@click.option("--source-url", default=None, help="Custom source URL for the PDF (e.g., drive link).")
def ingest_pdf_command(filepath: str, team_id: str, user_id: str, source_url: str):
    print(f"Ingesting from {filepath}...")
    document = extract_from_pdf(filepath, source_url=source_url)
    if document:
        result = process_and_save(document, filepath, team_id, content_type="book", user_id=user_id, chunked=True)
        print(f"Successfully created {result['chunk_count']} chunks.")
        print(f"Output saved to {result['output_file']}")
    else:
        print("Failed to extract content.")

if __name__ == "__main__":
    cli() 