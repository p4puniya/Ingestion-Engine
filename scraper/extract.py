import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import pdfplumber
from typing import Dict, Any, List
import trafilatura
import lxml.etree as ET
from dateutil import parser as dateparser
import json
import os
import re
from .chunker import auto_wrap_code_blocks, smart_join_pdf_lines, postprocess_markdown
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None
import openai
from prompts import get_author

# Import prompts configuration
try:
    from ..prompts import format_author_prompt, get_prompt_config
except ImportError:
    # Fallback if prompts module is not available
    def format_author_prompt(title_or_url, content_preview=None, mode="balanced"):
        if content_preview:
            return f"Who is the author:\n{title_or_url}\n\nContent preview: {content_preview}\n\nGive me only the author's name."
        else:
            return f"Who is the author:\n{title_or_url}\n\nGive me only the author's name."
    
    def get_prompt_config(mode="balanced"):
        configs = {
            "cost_saving": {"content_length": 200, "max_tokens": 32},
            "balanced": {"content_length": 500, "max_tokens": 64},
            "accuracy": {"content_length": 1000, "max_tokens": 128}
        }
        return configs.get(mode, configs["balanced"])

def extract_opengraph_and_jsonld(soup: BeautifulSoup) -> Dict:
    meta = {}
    # OpenGraph
    for tag in soup.find_all('meta'):
        if tag.get('property', '').startswith('og:'):
            key = tag['property'][3:]
            meta[key] = tag.get('content')
        if tag.get('name', '').startswith('article:'):
            key = tag['name'][8:]
            meta[key] = tag.get('content')
        if tag.get('name', '').lower() == 'author':
            meta['author'] = tag.get('content')
    # JSON-LD
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                if 'author' in data and isinstance(data['author'], dict) and 'name' in data['author']:
                    meta['author'] = data['author']['name']
                meta.update(data)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        if 'author' in item and isinstance(item['author'], dict) and 'name' in item['author']:
                            meta['author'] = item['author']['name']
                        meta.update(item)
        except Exception:
            continue
    return meta

def extract_author(soup: BeautifulSoup, html_content: str) -> str:
    # 1. Meta tags
    meta_author = (
        soup.find('meta', attrs={'name': 'author'}) or
        soup.find('meta', attrs={'property': 'article:author'}) or
        soup.find('meta', attrs={'property': 'og:author'}) or
        soup.find('meta', attrs={'name': 'twitter:creator'})
    )
    if meta_author and meta_author.get('content'):
        return meta_author['content'].strip()

    # 2. JSON-LD - Enhanced to handle @graph structures
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            
            # Handle @graph structure (common in WordPress)
            if isinstance(data, dict) and '@graph' in data:
                graph_data = data['@graph']
                if isinstance(graph_data, list):
                    for item in graph_data:
                        if isinstance(item, dict):
                            # Look for Person objects
                            if item.get('@type') == 'Person' and 'name' in item:
                                return item['name'].strip()
                            # Look for author field in any object
                            if 'author' in item:
                                author = item['author']
                                if isinstance(author, dict) and 'name' in author:
                                    return author['name'].strip()
                                elif isinstance(author, str):
                                    return author.strip()
            
            # Handle direct author field
            if isinstance(data, dict) and 'author' in data:
                author = data['author']
                if isinstance(author, dict) and 'name' in author:
                    return author['name'].strip()
                elif isinstance(author, list):
                    names = [a['name'] for a in author if isinstance(a, dict) and 'name' in a]
                    if names:
                        return ', '.join(names)
                elif isinstance(author, str):
                    return author.strip()
                    
            # Handle list of objects
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        if item.get('@type') == 'Person' and 'name' in item:
                            return item['name'].strip()
                        if 'author' in item:
                            author = item['author']
                            if isinstance(author, dict) and 'name' in author:
                                return author['name'].strip()
                            elif isinstance(author, str):
                                return author.strip()
        except Exception:
            continue

    # 3. Visible byline
    for selector in ['.author', '.byline', '.post-author', '.entry-author', '[itemprop=author]']:
        el = soup.select_one(selector)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)

    # 4. Fallback: scan for 'By ...' in the first 30 lines of visible text
    visible_text = soup.get_text(separator='\n')
    lines = visible_text.splitlines()
    for line in lines[:30]:
        m = re.match(r'By ([A-Za-z ,.-]+)$', line.strip(), re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # 5. Heuristic: scan first 30 lines for a name with a role (e.g., 'Firstname Lastname · Co-Founder at ...')
    name_role_keywords = ['co-founder', 'editor', 'ceo', 'cto', 'founder', 'chief', 'writer', 'author', 'lead', 'manager']
    for line in lines[:30]:
        l = line.strip()
        if re.match(r'^[A-Z][a-z]+ [A-Z][a-z]+( [A-Z][a-z]+)?[ \u00b7,\-]+', l):
            lower = l.lower()
            if any(kw in lower for kw in name_role_keywords):
                name_part = re.split(r'[·,\-]', l)[0].strip()
                return name_part

    # 6. New: Look for a standalone name near the top (first 10 lines) before or after the title
    # e.g., 'Nil Mamano' as a single line
    name_pattern = re.compile(r'^[A-Z][a-z]+ [A-Z][a-z]+$')
    for i, line in enumerate(lines[:10]):
        l = line.strip()
        if name_pattern.match(l):
            return l
    return ''

def extract_from_url(url: str, html_content: str = None, author_mode: str = "balanced") -> Dict[str, Any]:
    """
    Extracts the main content and metadata from a URL using a hybrid approach.
    Enhanced: Uses raw text as primary source to preserve code blocks, with trafilatura as fallback.
    Now uses auto_wrap_code_blocks for automatic code detection and wrapping.
    Author extraction uses content context, just like for PDFs.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    if html_content is None:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            html_content = response.text
        except requests.RequestException as e:
            print(f"Failed to fetch URL {url} with error: {e}")
            return None

    # Extract raw data first
    raw_data = extract_raw_from_url(url, html_content)

    soup_orig = BeautifulSoup(html_content, "html.parser")
    title = soup_orig.find("title").get_text() if soup_orig.find("title") else "No Title Found"

    # Enhanced metadata extraction
    meta = extract_opengraph_and_jsonld(soup_orig)
    date = meta.get('datePublished') or meta.get('date')
    tags = meta.get('keywords')
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(',')]
    elif not tags:
        tags = []

    # Use raw text as primary source to preserve code blocks
    if raw_data and raw_data.get('raw_text'):
        raw_text = raw_data['raw_text']
        raw_text = raw_text.replace('\\n', '\n')
        raw_text = re.sub(r'\n{3,}', '\n\n', raw_text)
        raw_text = re.sub(r' +', ' ', raw_text)
        markdown_content = auto_wrap_code_blocks(raw_text, mode='web')
        content_for_context = raw_text
    else:
        content_xml = trafilatura.extract(html_content, include_comments=False, output_format='xml')
        if not content_xml:
            main_content_html = str(soup_orig.find("article") or soup_orig.find("main") or soup_orig.body)
        else:
            soup_trafilatura = BeautifulSoup(content_xml, "lxml-xml")
            main_content_html = str(soup_trafilatura.find('main'))
        def html_to_markdown_with_headings(html):
            soup = BeautifulSoup(html, "html.parser")
            for i in range(1, 7):
                for tag in soup.find_all(f"h{i}"):
                    tag.insert_before(f"\n{'#'*i} {tag.get_text(strip=True)}\n")
                    tag.decompose()
            return soup.get_text()
        markdown_content = md(main_content_html, heading_style="ATX", strip=['a'], code_language='text')
        heading_count = len(re.findall(r'^#{1,6} ', markdown_content, re.MULTILINE))
        if heading_count <= 1:
            fallback_md = html_to_markdown_with_headings(main_content_html)
            markdown_content = fallback_md
        content_for_context = markdown_content

    # Use a content preview (context) for author extraction
    prompt_config = get_prompt_config(author_mode)
    context_length = prompt_config.get('content_length', 500)
    content_preview = content_for_context[:context_length]
    author = get_author(title, content_preview, mode=author_mode)

    return {
        'title': title,
        'content': markdown_content,
        'author': author,
        'date': date,
        'tags': tags,
        'source_url': url,
        'raw_data': raw_data,
        'context': content_preview,
        'metadata': {
            'title': title,
            'author': author,
            'date': date,
            'tags': tags,
            'source_url': url
        }
    }

def extract_structured_from_pdf(pdf_path, team_id="aline123", user_id="", source_url=None, author_mode="balanced"):
    if not fitz:
        raise ImportError("PyMuPDF (fitz) is not installed.")
    doc = fitz.open(pdf_path)
    items = []
    current_item = None
    font_sizes = []
    author_guess = None
    raw_text_lines = []
    
    # Enhanced author extraction using first 10 pages
    first_10_pages_text = extract_first_10_pages_content(pdf_path)
    
    # Use new unified author extraction with first 10 pages content
    title = source_url.split('/')[-1].split('\\')[-1] if source_url else os.path.basename(pdf_path)
    author_guess = get_author(title, first_10_pages_text, mode=author_mode)
    method = f"rule_based+openai_{author_mode}" if author_guess else "fallback"
    
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    font_sizes.append(span["size"])
                    # Collect raw text for smart joining
                    raw_text_lines.append(span["text"].strip())
    font_sizes.sort(reverse=True)
    title_font_threshold = font_sizes[max(1, len(font_sizes) // 10)] if font_sizes else 0
    for page_num, page in enumerate(doc, start=1):
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span["text"].strip()
                    font_size = span["size"]
                    if not text:
                        continue
                    if font_size >= title_font_threshold:
                        if current_item:
                            items.append(current_item)
                        current_item = {
                            "title": text,
                            "content": f"## {text}\n",
                            "content_type": "book",
                            "source_url": source_url or os.path.abspath(pdf_path),
                            "page_number": page_num,
                            "author": author_guess or "",
                            "user_id": user_id
                        }
                    else:
                        if current_item:
                            current_item["content"] += text + "\n"
                        else:
                            current_item = {
                                "title": "Untitled Section",
                                "content": text + "\n",
                                "content_type": "book",
                                "source_url": source_url or os.path.abspath(pdf_path),
                                "page_number": page_num,
                                "author": author_guess or "",
                                "user_id": user_id
                            }
    if current_item:
        items.append(current_item)
    # Debug output directory
    debug_dir = "debug_output"
    if not os.path.exists(debug_dir):
        os.makedirs(debug_dir)
    pdf_base = os.path.splitext(os.path.basename(pdf_path))[0]
    # Step 1: Raw extracted text
    raw_extracted = '\n'.join(raw_text_lines)
    with open(os.path.join(debug_dir, f"{pdf_base}_raw_extracted.txt"), "w", encoding="utf-8") as f:
        f.write(raw_extracted)
    # Step 2: Smart-joined text
    raw_text = smart_join_pdf_lines(raw_extracted)
    with open(os.path.join(debug_dir, f"{pdf_base}_smart_joined.txt"), "w", encoding="utf-8") as f:
        f.write(raw_text)
    # Step 3: Final raw_text
    with open(os.path.join(debug_dir, f"{pdf_base}_final_raw_text.txt"), "w", encoding="utf-8") as f:
        f.write(raw_text)
    # Convert to markdown for output
    markdown_content = postprocess_markdown(raw_text, mode='pdf')
    output_items = [{
        "title": title,
        "content": markdown_content,
        "content_type": "book",
        "source_url": source_url or os.path.abspath(pdf_path),
        "author": author_guess or "",
        "user_id": user_id
    }]
    
    # Create metadata with method information
    metadata = {
        "source_url": source_url or os.path.abspath(pdf_path),
        "title": title,
        "author": author_guess or "",
        "method": method,  # Include the author extraction method
        "content_type": "book"
    }
    
    return {
        "team_id": team_id,
        "items": output_items,
        "raw_text": raw_text,
        "metadata": metadata,  # Include metadata with method
        "method": method
    }

def extract_from_pdf_plumber(file_path: str, source_url: str = None, author_mode: str = "balanced") -> Dict[str, Any]:
    """
    Extracts text content from a local PDF file and returns it in a structured format for heading-based chunking.
    Title extraction: (1) PDF metadata Title if present and non-empty; (2) Largest text on first page; (3) Filename fallback.
    Sets author to 'Aline Lerner' if the book is hers. Allows custom source_url. Adds tags.
    Uses line-based extraction for better chunking and markdown.
    """
    lines: List[Dict] = []
    raw_text_lines = []
    try:
        with pdfplumber.open(file_path) as pdf:
            # 1. Try PDF metadata Title
            raw_title = pdf.metadata.get("Title") if pdf.metadata else None
            title = raw_title.strip() if raw_title and raw_title.strip() else None
            # 2. If no good title, use largest text on first page
            if not title and pdf.pages:
                first_page = pdf.pages[0]
                words = first_page.extract_words(extra_attrs=["size"])
                if words:
                    largest = max(words, key=lambda w: w.get("size", 0))
                    if largest and largest.get("text") and len(largest["text"].strip()) > 3:
                        title = largest["text"].strip()
            # 3. Fallback to filename (use source_url if provided, otherwise file_path)
            if not title:
                if source_url:
                    title = source_url.split('/')[-1].split('\\')[-1]
                else:
                    title = file_path.split('/')[-1].split('\\')[-1]
            # Author logic - enhanced extraction
            author = pdf.metadata.get("Author") if pdf.metadata else None
            # If author is empty, try to heuristically extract from first page
            if (not author or not author.strip()) and pdf.pages:
                first_page_text = pdf.pages[0].extract_text() or ""
                # Look for various author patterns
                for line in first_page_text.splitlines():
                    line = line.strip()
                    # Pattern 1: "By John Doe"
                    m = re.match(r'By ([A-Za-z ,.-]+)$', line, re.IGNORECASE)
                    if m:
                        author = m.group(1).strip()
                        break
                    # Pattern 2: "Author: John Doe"
                    m = re.match(r'Author: ([A-Za-z ,.-]+)$', line, re.IGNORECASE)
                    if m:
                        author = m.group(1).strip()
                        break
                    # Pattern 3: "Written by John Doe"
                    m = re.match(r'Written by ([A-Za-z ,.-]+)$', line, re.IGNORECASE)
                    if m:
                        author = m.group(1).strip()
                        break
                    # Pattern 4: Look for names after "by" in the middle of lines
                    m = re.search(r'\bby\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', line, re.IGNORECASE)
                    if m:
                        author = m.group(1).strip()
                        break
            # Special case for Aline Lerner's books
            if (title and 'aline' in title.lower()) or (file_path and 'aline' in file_path.lower()):
                author = "Aline Lerner"
            # Source URL logic
            src_url = source_url or file_path
            # Tags
            tags = ["book", "technical interview"]
            metadata = {
                "source_url": src_url,
                "title": title,
                "author": author,
                "date": pdf.metadata.get("CreationDate") if pdf.metadata else None,
                "tags": tags,
            }
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    # Try to get font size info by matching words on the line
                    words = page.extract_words(extra_attrs=["size", "top"])
                    sizes = [w["size"] for w in words if w["text"].strip() in line and w.get("size")]
                    avg_size = sum(sizes) / len(sizes) if sizes else 0
                    # Use the y position of the first word in the line if available
                    y = None
                    for w in words:
                        if w["text"].strip() in line and w.get("top"):
                            y = round(w["top"], 1)
                            break
                    lines.append({"text": line, "size": avg_size, "y": y, "page": page.page_number})
                    raw_text_lines.append(line)
            
            # If still no author, try to extract from the first few lines of content (after text extraction)
            if not author and raw_text_lines:
                # Look for author names in the first 20 lines
                for i, line in enumerate(raw_text_lines[:20]):
                    line = line.strip()
                    # Pattern 1: Look for lines that look like author names (proper case, 2-4 words, or all uppercase)
                    if (re.match(r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*$', line) or re.match(r'^[A-Z .\-]{4,}$', line)) and 2 <= len(line.split()) <= 4:
                        # Avoid common words that might be mistaken for names
                        if line.lower() not in ['beyond cracking', 'coding interview', 'technical interview', 'careercup llc', 'palo alto ca']:
                            # Check if the next few lines also look like author names
                            author_candidates = [line]
                            for j in range(i+1, min(i+4, len(raw_text_lines))):
                                next_line = raw_text_lines[j].strip()
                                if (re.match(r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*$', next_line) or re.match(r'^[A-Z .\-]{4,}$', next_line)) and 2 <= len(next_line.split()) <= 4:
                                    if next_line.lower() not in ['beyond cracking', 'coding interview', 'technical interview', 'careercup llc', 'palo alto ca']:
                                        author_candidates.append(next_line)
                            # If we found multiple author candidates, join them
                            if len(author_candidates) > 1:
                                author = ', '.join(author_candidates)
                            else:
                                author = author_candidates[0]
                            break
        # Debug output directory
        debug_dir = "debug_output"
        if not os.path.exists(debug_dir):
            os.makedirs(debug_dir)
        pdf_base = os.path.splitext(os.path.basename(file_path))[0]
        # Step 1: Raw extracted text
        raw_extracted = '\n'.join(raw_text_lines)
        with open(os.path.join(debug_dir, f"{pdf_base}_raw_extracted.txt"), "w", encoding="utf-8") as f:
            f.write(raw_extracted)
        # Step 2: Smart-joined text
        raw_text = smart_join_pdf_lines(raw_extracted)
        with open(os.path.join(debug_dir, f"{pdf_base}_smart_joined.txt"), "w", encoding="utf-8") as f:
            f.write(raw_text)
        # Step 3: Final raw_text
        with open(os.path.join(debug_dir, f"{pdf_base}_final_raw_text.txt"), "w", encoding="utf-8") as f:
            f.write(raw_text)
        # Convert to markdown for output
        markdown_content = postprocess_markdown(raw_text, mode='pdf')
        
        # Get first 10 pages text for author extraction
        first_10_pages_text = extract_first_10_pages_content(file_path)
        
        # Use new unified author extraction with first 10 pages content
        author_guess = get_author(title, first_10_pages_text, mode=author_mode)
        method = f"rule_based+openai_{author_mode}" if author_guess else "fallback"
        
        # Update metadata to include the method and final author
        metadata.update({
            "author": author_guess or "",
            "method": method
        })
        output_items = [{
            "title": title,
            "content": markdown_content,
            "content_type": "book",
            "source_url": src_url,
            "author": author_guess or "",
            "user_id": ""
        }]
        return {
            "items": output_items,
            "metadata": metadata,
            "raw_text": raw_text,
            "method": method
        }
    except Exception as e:
        print(f"Error reading PDF file: {e}")
        return None

def extract_from_pdf(file_path: str, source_url: str = None, author_mode: str = "balanced") -> dict:
    if fitz:
        try:
            return extract_structured_from_pdf(file_path, source_url=source_url, author_mode=author_mode)
        except Exception as e:
            print(f"[fitz] PDF extraction failed: {e}, falling back to pdfplumber.")
    return extract_from_pdf_plumber(file_path, source_url=source_url, author_mode=author_mode)

def extract_raw_content(html_content: str) -> str:
    """Extract raw content without any formatting or processing."""
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()
    
    # Get all text content
    raw_text = soup.get_text()
    
    # Clean up whitespace but preserve structure
    lines = raw_text.split('\n')
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if line:  # Only keep non-empty lines
            cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines)

def extract_raw_from_url(url: str, html_content: str = None) -> Dict[str, Any]:
    """
    Extracts raw content from a URL without any processing or formatting.
    Returns the raw HTML, raw text, and all code blocks found.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    if html_content is None:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            html_content = response.text
        except requests.RequestException as e:
            print(f"Failed to fetch URL {url} with error: {e}")
            return None

    # Extract raw text
    raw_text = extract_raw_content(html_content)
    
    # Extract all code blocks
    soup = BeautifulSoup(html_content, "html.parser")
    code_blocks = []
    for i, code in enumerate(soup.find_all(['code', 'pre'])):
        code_text = code.get_text().strip()
        if code_text:
            code_blocks.append({
                'index': i,
                'content': code_text,
                'element_type': code.name
            })
    
    # Extract basic metadata
    title = soup.find("title").get_text() if soup.find("title") else "No Title Found"
    
    return {
        "raw_html": html_content,
        "raw_text": raw_text,
        "code_blocks": code_blocks,
        "metadata": {
            "source_url": url,
            "title": title,
            "html_length": len(html_content),
            "text_length": len(raw_text),
            "code_block_count": len(code_blocks)
        }
    }

def get_author_via_openai(title_or_url, is_pdf=True, pdf_content=None, mode="balanced"):
    api_key = os.getenv('OPENAI_API_KEY')
    print(f"[DEBUG] get_author_via_openai called with: {title_or_url}, mode: {mode}")
    print(f"[DEBUG] OpenAI API key found: {'Yes' if api_key else 'No'}")
    if api_key:
        print(f"[DEBUG] OpenAI API key starts with: {api_key[:8]}...")
    
    if not api_key:
        print("[Author Extraction] OpenAI API key not found, using fallback method")
        return None, "fallback"
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        # Get prompt configuration for the mode
        config = get_prompt_config(mode)
        content_length = config["content_length"]
        max_tokens = config["max_tokens"]
        model = config.get("model", "gpt-3.5-turbo")
        
        # Build a better prompt with more context
        if is_pdf and pdf_content:
            # Use the specified amount of PDF content for context
            content_preview = pdf_content[:content_length].replace('\n', ' ').strip()
            prompt = format_author_prompt(title_or_url, content_preview, mode)
        else:
            prompt = format_author_prompt(title_or_url, mode=mode)
        
        print(f"[DEBUG] Using mode '{mode}' - content length: {content_length}, max tokens: {max_tokens}, model: {model}")
        print(f"[DEBUG] About to call OpenAI API with prompt: {prompt[:100]}...")
        print(f"[Author Extraction] Using OpenAI API for: {title_or_url}")
        
        # Log the full prompt being sent
        print(f"\n🔍 FULL PROMPT BEING SENT TO OPENAI:")
        print("=" * 60)
        print(prompt)
        print("=" * 60)
        
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0
        )
        
        author = response.choices[0].message.content.strip()
        print(f"\n🤖 FULL OPENAI RESPONSE:")
        print("=" * 60)
        print(f"Response: '{author}'")
        print(f"Model: {response.model}")
        print(f"Usage: {response.usage}")
        print("=" * 60)
        
        if author.lower() == 'unknown' or not author:
            print(f"[Author Extraction] OpenAI returned 'Unknown' or empty, using fallback")
            return None, "fallback"
        
        print(f"[Author Extraction] OpenAI found author: {author}")
        return author, f"openai_{mode}"
        
    except Exception as e:
        print(f"[DEBUG] OpenAI API call failed with error: {e}")
        print(f"[Author Extraction] OpenAI API failed: {e}, using fallback")
        return None, "fallback"

def extract_first_10_pages_content(pdf_path):
    """
    Extract text content from the first 10 pages of a PDF file.
    Returns the combined text from pages 1-10 (or all pages if less than 10).
    """
    try:
        if fitz:
            # Use PyMuPDF (fitz)
            doc = fitz.open(pdf_path)
            pages_to_extract = min(10, doc.page_count)
            content_parts = []
            
            for page_num in range(pages_to_extract):
                page = doc[page_num]
                page_text = page.get_text()
                if page_text.strip():
                    content_parts.append(f"--- Page {page_num + 1} ---\n{page_text}")
            
            doc.close()
            return "\n\n".join(content_parts)
        else:
            # Fallback to pdfplumber
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                pages_to_extract = min(10, len(pdf.pages))
                content_parts = []
                
                for page_num in range(pages_to_extract):
                    page = pdf.pages[page_num]
                    page_text = page.extract_text()
                    if page_text and page_text.strip():
                        content_parts.append(f"--- Page {page_num + 1} ---\n{page_text}")
                
                return "\n\n".join(content_parts)
    except Exception as e:
        print(f"Error extracting first 10 pages: {e}")
        return ""
