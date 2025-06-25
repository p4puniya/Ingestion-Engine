"""
Author extraction module using hybrid approach: rule-based + OpenAI fallback.
"""

import re
import openai

# -- Prompt Templates --

AUTHOR_EXTRACTION_PROMPT_FIXED = """
You are an expert assistant in finding author names from documents. You are given a title or a URL and a content preview.
You should use the internet to find the author name.
Task: Extract the name(s) of the author(s) by searching the internet based on the title or the content preview.

If there are multiple authors, list them all separated by commas.
You are not allowed to make up an author name.
If there is only one author, provide just that name.
If no author can be determined, respond with "Unknown".
After finding the authors, re-analyze the content to check if it is a valid human name. If not, remove the author from the list.

Respond only with the author name(s). Do not say anything else.

Title or URL: {title_or_url}

Content Preview:
{content_preview}
"""

AUTHOR_EXTRACTION_PROMPT_SIMPLE = """
Who is/are the author(s):
{title_or_url}

If multiple authors, list them separated by commas.
Give me only the author name(s).
"""

PROMPT_CONFIGS = {
    "cost_saving": {
        "content_length": 2000,
        "max_tokens": 64,
        "prompt_template": AUTHOR_EXTRACTION_PROMPT_SIMPLE,
        "model": "gpt-3.5-turbo"
    },
    "balanced": {
        "content_length": 5000,
        "max_tokens": 128,
        "prompt_template": AUTHOR_EXTRACTION_PROMPT_FIXED,
        "model": "gpt-3.5-turbo"
    },
    "accuracy": {
        "content_length": 10000,
        "max_tokens": 256,
        "prompt_template": AUTHOR_EXTRACTION_PROMPT_FIXED,
        "model": "gpt-4"  # Change to gpt-4o if needed
    }
}

# -- Rule-Based Extraction --

def extract_author_from_text(text):
    """Try to extract author(s) from raw text using simple regex patterns."""
    authors = []
    
    # Pattern 1: "By John Doe" or "By John Doe and Jane Smith"
    matches = re.findall(r'(?:By|by)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)+(?:\s+and\s+[A-Z][a-z]+(?:\s[A-Z][a-z]+)+)*)', text, re.IGNORECASE)
    for match in matches:
        # Split by "and" to get individual authors
        if ' and ' in match.lower():
            parts = re.split(r'\s+and\s+', match, flags=re.IGNORECASE)
            authors.extend(parts)
        else:
            authors.append(match)
    
    # Pattern 2: "Author: John Doe"
    matches = re.findall(r'Author:\s*([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)', text, re.IGNORECASE)
    authors.extend(matches)
    
    # Pattern 3: "Written by John Doe"
    matches = re.findall(r'Written by\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)', text, re.IGNORECASE)
    authors.extend(matches)
    
    # Pattern 4: Look for names after "by" in the middle of lines
    matches = re.findall(r'\bby\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', text, re.IGNORECASE)
    authors.extend(matches)
    
    # Pattern 5: Look for multiple author lines (common in books)
    # Lines that look like author names (proper case, 2-4 words, or all uppercase)
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if (re.match(r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*$', line) or 
            re.match(r'^[A-Z .\-]{4,}$', line)) and 2 <= len(line.split()) <= 4:
            # Avoid common words that might be mistaken for names
            if line.lower() not in ['beyond cracking', 'coding interview', 'technical interview', 
                                   'careercup llc', 'palo alto ca', 'copyright', 'all rights reserved',
                                   'introduction', 'preface', 'table of contents']:
                authors.append(line)
    
    # Clean up and remove duplicates
    unique_authors = []
    for author in authors:
        author = author.strip()
        # Skip if empty or too short
        if not author or len(author) < 3:
            continue
        # Skip if it's just common words
        if author.lower() in ['by', 'author', 'written', 'co-author', 'contributors']:
            continue
        # Add if not already in list (case-insensitive)
        if not any(author.lower() == existing.lower() for existing in unique_authors):
            unique_authors.append(author)
    
    # Validate and filter authors
    valid_authors = clean_and_validate_authors(unique_authors)
    
    if valid_authors:
        return ', '.join(valid_authors)
    return None

# -- OpenAI API Fallback --

def extract_author_using_openai(title_or_url, content_preview=None, mode="balanced"):
    config = PROMPT_CONFIGS[mode]
    prompt = config["prompt_template"].format(
        title_or_url=title_or_url,
        content_preview=content_preview or ""
    )
    
    try:
        from openai import OpenAI
        client = OpenAI()
        
        response = client.chat.completions.create(
            model=config["model"],
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=config["max_tokens"],
            temperature=0
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"OpenAI call failed: {e}")
        return None

# -- Unified Interface --

def get_author(title_or_url, content_preview="", mode="balanced"):
    """
    Extract author from content preview and title using:
    1. Regex-based quick pass
    2. Fallback to OpenAI API if not found
    """
    # Try rule-based first
    author = extract_author_from_text(content_preview)
    if author:
        return author

    # Truncate content based on mode's content_length limit
    config = PROMPT_CONFIGS[mode]
    max_length = config["content_length"]
    if len(content_preview) > max_length:
        content_preview = content_preview[:max_length] + "..."
    
    # Fallback to OpenAI
    return extract_author_using_openai(title_or_url, content_preview, mode)

def is_valid_human_name(name: str) -> bool:
    name = name.strip()

    # Rule out very short names
    if len(name) < 5:
        return False

    # Rule out all uppercase acronyms (e.g., "C C I")
    if name.replace(" ", "").isupper() and len(name.split()) <= 3:
        return False

    # Rule out non-alphabetical words (no digits or symbols)
    if re.search(r"[^a-zA-Z\s\.\'-]", name):
        return False

    # Require at least 2 capitalized words (e.g., "Aline Lerner")
    parts = name.split()
    if len(parts) < 2:
        return False
    if not all(part[0].isupper() and part[1:].islower() for part in parts if len(part) > 1):
        return False

    return True

def clean_and_validate_authors(authors_list):
    """
    Clean and validate a list of potential authors.
    Returns only valid human names.
    """
    valid_authors = []
    
    for author in authors_list:
        author = author.strip()
        if is_valid_human_name(author):
            valid_authors.append(author)
    
    return valid_authors 