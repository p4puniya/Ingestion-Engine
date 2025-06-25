import uuid
import re
from typing import List, Dict, Union

# Try to load spaCy, fallback to None
try:
    import spacy
    nlp = spacy.load("en_core_web_sm")
except Exception:
    nlp = None

# Fallback: TF-IDF
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
except ImportError:
    TfidfVectorizer = None

def is_code_line(line: str, mode: str = "web") -> bool:
    if len(line.strip()) == 0:
        return False
    if mode == "pdf":
        # Only match lines that look like real code/commands for PDFs
        if re.match(r'^(def |class |CREATE |GRANT |SELECT |INSERT |UPDATE |DELETE |DROP |ALTER |USE |SHOW |DESCRIBE )', line.strip(), re.IGNORECASE):
            return True
        if re.match(r'^\s{4,}', line):  # 4+ leading spaces
            return True
        if re.match(r'^[\$\#].*', line.strip()):  # Shell prompt
            return True
        return False
    # Web/URL logic (existing)
    line_lower = line.lower().strip()
    if any(skip in line_lower for skip in [
        'quickstart', 'navigation', 'admin portal', 'create a dashboard', 
        'learn more', 'search', 'ask ai', 'copy', 'to create a read-only user',
        'postgresql', 'big query', 'snowflake', 'mysql', 'do the following',
        'grant connect privileges', 'grant usage on the schema', 'grant select privileges',
        'the connection string', 'go to', 'if you\'re using', 'for more information',
        'the quill platform', 'create a cleaned schema', 'next steps', 'once you have',
        'check out our guides', 'build your first dashboard', 'powered by', 'on this page'
    ]):
        return False
    if re.search(r'[;{}<>=()\'"`\[\]#@$]|  ', line):
        return True
    if re.match(r'^\s{2,}', line):  # leading spaces
        return True
    if re.match(r'^(>>>|\$|--|\|)', line.strip()):
        return True
    if re.search(r'\b(CREATE|GRANT|SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|USE|SHOW|DESCRIBE)\b', line, re.IGNORECASE):
        return True
    if re.search(r'://.*@.*:', line):
        return True
    return False

def auto_wrap_code_blocks(text: str, mode: str = "web") -> str:
    lines = text.splitlines()
    output = []
    buffer = []
    already_code_wrapped = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if buffer:
                cleaned = [b for b in buffer if b.strip()]
                if cleaned:
                    output.append("```")
                    output.extend(cleaned)
                    output.append("```")
                buffer = []
            output.append(line)
            already_code_wrapped = not already_code_wrapped
            continue
        if already_code_wrapped:
            output.append(line)
            continue
        if is_code_line(line, mode=mode):
            buffer.append(line)
        else:
            if buffer:
                cleaned = [b for b in buffer if b.strip()]
                if cleaned:
                    output.append("```")
                    output.extend(cleaned)
                    output.append("```")
                buffer = []
            output.append(line)
    if buffer:
        cleaned = [b for b in buffer if b.strip()]
        if cleaned:
            output.append("```")
            output.extend(cleaned)
            output.append("```")
    return '\n'.join(output)

def extract_tags_spacy(text: str, top_n: int = 5) -> List[str]:
    if not nlp:
        return []
    doc = nlp(text)
    tags = set()
    for chunk in doc.noun_chunks:
        tags.add(chunk.lemma_.lower())
    for ent in doc.ents:
        tags.add(ent.text.lower())
    if len(tags) < top_n:
        tokens = [t.lemma_.lower() for t in doc if t.is_alpha and not t.is_stop]
        tags.update(tokens)
    return list(tags)[:top_n]

def extract_tags_tfidf(texts: List[str], top_n: int = 5) -> List[List[str]]:
    if not TfidfVectorizer or not texts or all(not t.strip() for t in texts):
        return [[] for _ in texts]
    try:
        vectorizer = TfidfVectorizer(stop_words='english', max_features=50)
        X = vectorizer.fit_transform(texts)
        features = vectorizer.get_feature_names_out()
        tags_per_chunk = []
        for row in X:
            indices = row.toarray().flatten().argsort()[::-1][:top_n]
            tags = [features[i] for i in indices if row[0, i] > 0]
            tags_per_chunk.append(tags)
        return tags_per_chunk
    except ValueError as e:
        # Handle case where vocabulary is empty (only stop words)
        if "empty vocabulary" in str(e):
            return [[] for _ in texts]
        else:
            raise e

def is_garbage_line(text: str) -> bool:
    garbage_patterns = [
        # r'table of contents', r'copyright', r'all rights reserved', r'isbn', r'publisher',
        # r'amazon', r'www\.', r'http[s]?://', r'\bpage \d+\b', r'\b\d{1,3}\b',
        # r'\bcontents\b', r'\bindex\b', r'\bforeword\b',
        # r'\babout the author\b', r'\bcontact', r'\bdisclaimer', r'\bno part of this',
        # r'\bprinted in', r'\bpress', r'\bpublication', r'\bcover design', r'\bvisit',
        # r'\bemail', r'\bwebsite', r'\b\d{4}\b',
    ]
    text_l = text.lower().strip()
    return any(re.search(pat, text_l) for pat in garbage_patterns)

def postprocess_markdown(text: str, mode: str = 'web') -> str:
    print("[DEBUG] Before postprocess_markdown:\n" + text[:1000] + ("..." if len(text) > 1000 else ""))
    
    # First, auto-wrap any code blocks that aren't already wrapped
    text = auto_wrap_code_blocks(text, mode=mode)
    
    # Clean up the text formatting
    lines = text.splitlines()
    processed = []
    in_code = False
    
    for line in lines:
        l = line.strip()
        # Preserve existing code blocks
        if l.startswith('```'):
            if in_code:
                processed.append('```')
                in_code = False
            else:
                in_code = True
                processed.append(line)
            continue
        if in_code:
            processed.append(line)
            continue
        # Process non-code lines
        if re.match(r'^(\u0001|\u0002|\u0003|\-|\*|\u2022)\s+', l):
            l = re.sub(r'^(\-|\u2022|\*)\s+', '* ', l)
        l = re.sub(r'(https?://\S+)', r'[\1](\1)', l)
        l = re.sub(r'\b(www\.[^\s]+)', r'[\1](http://\1)', l)
        processed.append(l)
    if in_code:
        processed.append('```')
    
    # Clean up excessive blank lines and formatting
    out = []
    last_blank = False
    for l in processed:
        if l.strip() == '':
            if not last_blank:
                out.append('')
            last_blank = True
        else:
            out.append(l)
            last_blank = False
    
    result = '\n'.join(out).strip()
    
    # Final cleanup: remove excessive whitespace and normalize formatting
    result = re.sub(r'\n{3,}', '\n\n', result)  # Max 2 consecutive newlines
    result = re.sub(r' +', ' ', result)  # Multiple spaces to single space
    
    print("[DEBUG] After postprocess_markdown:\n" + result[:1000] + ("..." if len(result) > 1000 else ""))
    return result

def smart_join_pdf_lines(text: str) -> str:
    lines = text.splitlines()
    output = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if i < len(lines) - 1:
            next_line = lines[i + 1]
            # If line ends with a word and next line starts with lowercase/digit, join with space
            if (
                re.search(r'[a-zA-Z0-9]$', line.strip()) and
                re.match(r'^[a-z0-9]', next_line.strip())
            ):
                output.append(line.rstrip() + ' ' + next_line.lstrip())
                i += 2
                continue
        output.append(line)
        i += 1
    return '\n'.join([l for l in output if l.strip()])

def chunk_pdf_by_headings(lines: List[Dict], metadata: Dict, min_heading_font: float = None) -> List[Dict]:
    # Join lines smartly before further processing
    joined_lines = []
    for line in lines:
        # If the line is a dict with 'text', process it
        if isinstance(line, dict) and 'text' in line:
            line['text'] = smart_join_pdf_lines(line['text']) if '\n' in line['text'] else line['text']
        joined_lines.append(line)
    lines = joined_lines
    font_sizes = [line["size"] for line in lines if line["size"]]
    if not font_sizes:
        min_heading_font = None
    elif min_heading_font is None:
        font_sizes_sorted = sorted(font_sizes)
        min_heading_font = font_sizes_sorted[int(0.9 * len(font_sizes))] if font_sizes_sorted else 0

    # Heading patterns: classic + all-caps multi-word
    heading_patterns = [
        re.compile(r"^chapter\s*\d+", re.IGNORECASE),
        re.compile(r"^section\s*\d+", re.IGNORECASE),
        re.compile(r"^part\s*\d+", re.IGNORECASE),
        re.compile(r"^ch\s*\d+", re.IGNORECASE),
        re.compile(r"^\d+\.\s+"),
        re.compile(r"^\d+\s+"),
        re.compile(r"^\d+\.\d+"),
    ]
    def is_allcaps_heading(text):
        # At least 2 words, all caps, possibly with spaces between letters
        words = text.split()
        if len(words) < 2:
            return False
        # Remove spaces and check if all letters are uppercase or non-alpha
        joined = ''.join(words)
        return joined.isupper() and any(c.isalpha() for c in joined)

    chunks = []
    current_chunk = []
    current_title = None
    for i, line in enumerate(lines):
        text = line["text"].strip()
        size = line["size"]
        if not text or is_garbage_line(text):
            continue
        # Heading detection: classic or all-caps multi-word
        is_heading = False
        for pat in heading_patterns:
            if pat.match(text):
                is_heading = True
                break
        if not is_heading and is_allcaps_heading(text):
            is_heading = True
        if is_heading:
            # Save previous chunk
            if current_chunk and current_title:
                chunk_text = "\n".join(current_chunk).strip()
                if chunk_text:
                    chunks.append({
                        "id": str(uuid.uuid4()),
                        "source": metadata.get("source_url"),
                        "content": f"## {current_title}\n\n" + postprocess_markdown(chunk_text, mode='pdf'),
                        "metadata": metadata.copy(),
                    })
            current_title = text
            current_chunk = []
        else:
            current_chunk.append(text)
    # Save last chunk
    if current_chunk and current_title:
        chunk_text = "\n".join(current_chunk).strip()
        if chunk_text:
            chunks.append({
                "id": str(uuid.uuid4()),
                "source": metadata.get("source_url"),
                "content": f"## {current_title}\n\n" + postprocess_markdown(chunk_text, mode='pdf'),
                "metadata": metadata.copy(),
            })
    # Fallback: if no real headings found, aggregate all content into one chunk
    if not chunks:
        all_content = "\n".join([line["text"].strip() for line in lines if line["text"].strip() and not is_garbage_line(line["text"])])
        chunks = [{
            "id": str(uuid.uuid4()),
            "source": metadata.get("source_url"),
            "content": postprocess_markdown(all_content, mode='pdf'),
            "metadata": metadata.copy(),
        }]
    # Merge small chunks (<300 chars) with previous
    merged_chunks = []
    for chunk in chunks:
        if merged_chunks and len(chunk["content"]) < 300:
            merged_chunks[-1]["content"] += "\n\n" + chunk["content"]
        else:
            merged_chunks.append(chunk)
    return merged_chunks

def chunk_document(document: Dict) -> List[Dict]:
    content = document.get("content", "")
    metadata = document.get("metadata", {})
    
    # Handle the new simplified structure from extract.py
    if not metadata and document.get("source_url"):
        metadata = {
            "source_url": document.get("source_url"),
            "title": document.get("title"),
            "author": document.get("author"),
            "date": document.get("date"),
            "tags": document.get("tags", [])
        }
    
    if isinstance(content, list) and content and isinstance(content[0], dict):
        chunks = chunk_pdf_by_headings(content, metadata)
    else:
        heading_pattern = re.compile(r'(^|\n)(#{1,6} .*)')
        matches = list(heading_pattern.finditer(content))
        chunks = []
        if matches:
            for i, match in enumerate(matches):
                start = match.start(2)
                end = matches[i+1].start(2) if i+1 < len(matches) else len(content)
                chunk_content = content[start:end].strip()
                if chunk_content:
                    chunks.append({
                        "id": str(uuid.uuid4()),
                        "source": metadata.get("source_url"),
                        "content": postprocess_markdown(chunk_content),
                        "metadata": metadata.copy(),
                    })
        else:
            for chunk_content in content.split('\n\n'):
                if chunk_content.strip():
                    chunks.append({
                        "id": str(uuid.uuid4()),
                        "source": metadata.get("source_url"),
                        "content": postprocess_markdown(chunk_content.strip()),
                        "metadata": metadata.copy(),
                    })

    if nlp:
        for chunk in chunks:
            chunk["metadata"]["tags"] = extract_tags_spacy(chunk["content"])
    elif TfidfVectorizer:
        texts = [chunk["content"] for chunk in chunks]
        tags_list = extract_tags_tfidf(texts)
        for chunk, tags in zip(chunks, tags_list):
            chunk["metadata"]["tags"] = tags
    else:
        for chunk in chunks:
            chunk["metadata"]["tags"] = []
    return chunks

def extract_title_from_content(content: str, metadata: dict = None) -> str:
    # 1. Prefer metadata title if available and non-generic
    if metadata:
        meta_title = metadata.get("title")
        if meta_title and meta_title.strip().lower() not in ["no title found", "untitled", "", None]:
            return meta_title.strip()[:120]
    # 2. Prefer first Markdown heading
    lines = content.strip().split('\n')
    for line in lines:
        if re.match(r'^\s*#{1,6}\s+.+', line):
            return re.sub(r'^#{1,6}\s+', '', line).strip()
    # 3. Fallback: first non-empty line
    for line in lines:
        if line.strip():
            return line.strip()[:80]  # limit length
    return "Untitled"

def format_chunks_for_ingestion(chunks: List[Dict], user_id: str = "default_user") -> List[Dict]:
    allowed_types = [
        "blog", "podcast_transcript", "call_transcript", "linkedin_post", "reddit_comment", "book", "other"
    ]
    def guess_content_type(chunk):
        meta = chunk.get("metadata", {})
        if "content_type" in meta and meta["content_type"] in allowed_types:
            return meta["content_type"]
        src = chunk.get("source", "")
        if src and (src.endswith('.pdf') or ".pdf" in src or "book" in src.lower()):
            return "book"
        if src and (src.startswith("http://") or src.startswith("https://")):
            return "blog"
        return "other"
    items = []
    for chunk in chunks:
        title_guess = extract_title_from_content(chunk["content"], chunk.get("metadata", {}))
        items.append({
            "title": title_guess or "Untitled Chapter",
            "content": format_markdown(chunk["content"]),
            "content_type": guess_content_type(chunk),
            "source_url": chunk.get("source"),
            "author": chunk["metadata"].get("author", ""),
            "author_method": chunk["metadata"].get("method", ""),
            "user_id": user_id or "default_user"
        })
    return items

def generate_ingestion_payload(document: Dict, team_id: str = "aline123", user_id: str = "default_user") -> Dict:
    chunks = chunk_document(document)
    items = format_chunks_for_ingestion(chunks, user_id=user_id)
    return {
        "team_id": team_id,
        "items": items
    }

def format_markdown(text: str) -> str:
    # Replace literal \n strings with actual newlines
    text = text.replace('\\n', '\n')
    
    # Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # Ensure code blocks are surrounded by blank lines
    text = re.sub(r'(?<!\n)```', r'\n```', text)
    text = re.sub(r'```(?!\n)', r'```\n', text)

    # Add spacing between headings and content
    text = re.sub(r'(#+ .+)\n(?!\n)', r'\1\n\n', text)

    # Add spacing between paragraphs
    text = re.sub(r'(?<!\n)\n(?=\S)', '\n\n', text)

    return text.strip()

def generate_raw_payload(document: Dict, team_id: str = "aline123", user_id: str = "default_user") -> Dict:
    """
    Generates a raw payload without any processing, chunking, or formatting.
    Returns the raw data exactly as extracted from the source.
    """
    raw_data = document.get("raw_data", {})
    if not raw_data:
        # Prefer smart-joined raw_text if present (PDFs)
        raw_text = document.get("raw_text") or document.get("content", "")
        raw_data = {
            "raw_text": raw_text,
            "code_blocks": [],
            "metadata": document.get("metadata", {})
        }
    return {
        "team_id": team_id,
        "raw_data": raw_data,
        "user_id": user_id,
        "extraction_timestamp": str(uuid.uuid4())  # Simple timestamp
    }