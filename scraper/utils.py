def build_output(chunks, team_id, content_type, source_url, author=None, user_id=None, title=None):
    items = []
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        items.append({
            "title": meta.get("title") or title or "Untitled",
            "content": chunk["content"],
            "content_type": content_type,
            "source_url": source_url,
            "author": meta.get("author") or author or "",
            "user_id": user_id or "",
        })
    return {"team_id": team_id, "items": items}
