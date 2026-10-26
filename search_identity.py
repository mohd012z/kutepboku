"""Conservative identity helpers for Search Engine V2.

Only strong identifiers are merged; ambiguous title-only records stay distinct.
"""
import copy
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, unquote

def _norm(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())

def normalize_query(text: str) -> str:
    value = _norm(text)[:200]
    value = re.sub(r"^(?:please\s+)?(?:find\s+me|search\s+for|show\s+me)\s+(?:(?:some|the)\s+)?(?:books?\s+)?(?:about\s+|on\s+)?", "", value)
    return value.strip()

def _url(value):
    try:
        p = urlsplit(str(value or "").strip())
        if p.scheme not in ("http","https") or not p.hostname:
            return ""
        params = [(k,v) for k,v in parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in ("fbclid","gclid")]
        return urlunsplit((p.scheme.lower(),p.hostname.lower() + ((":"+str(p.port)) if p.port else ""),unquote(p.path).rstrip("/"),urlencode(params),""))
    except (ValueError,TypeError):
        return ""

def book_identity(book: dict) -> str:
    for key,prefix in (("work_id","work"),("ia_identifier","ia"),("archive_identifier","ia"),("gutenberg_id","gutenberg")):
        if book.get(key):
            return prefix+":"+_norm(book[key])
    url = _url(book.get("source_url") or book.get("url") or "")
    p = urlsplit(url)
    path = p.path.split("/")
    if p.hostname in ("archive.org","www.archive.org") and len(path)>2 and path[1] in ("details","download"):
        return "ia:"+_norm(path[2])
    title = _norm(book.get("title"))
    author = _norm(book.get("author") or book.get("authors"))
    if title and author:
        return "title-author:"+title+"|"+author
    return "url:"+url if url else "unknown:"+repr(sorted((str(k),str(v)) for k,v in book.items()))

def repo_identity(repo: dict) -> str:
    name = str(repo.get("full_name") or "").strip()
    if not name:
        url = _url(repo.get("html_url") or repo.get("url"))
        p = urlsplit(url)
        if p.hostname not in ("github.com","www.github.com"):
            return "repo-url:"+url
        name = p.path.strip("/")
    parts = name.removesuffix(".git").split("/")
    if len(parts)>=2 and all(re.fullmatch(r"[A-Za-z0-9_.-]+",part) for part in parts[:2]):
        return "repo:"+parts[0].casefold()+"/"+parts[1].casefold()
    return "repo-unknown:"+_norm(name)

def dedupe_candidates(items: list[dict], identity_fn) -> list[dict]:
    result=[]
    index={}
    for item in items:
        identity=identity_fn(item)
        source=str(item.get("source") or item.get("source_url") or item.get("html_url") or "")
        if identity not in index:
            record=copy.deepcopy(item)
            record["provenance"]=[source] if source else []
            index[identity]=len(result)
            result.append(record)
        else:
            current=result[index[identity]]
            if source and source not in current["provenance"]:
                current["provenance"].append(source)
    return result
