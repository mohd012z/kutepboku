"""Global (non-GitHub) source discovery — key-free, parallel, fail-open.

Extends Find ALL beyond GitHub: npm (JS), crates.io (Rust), Docker Hub
(images) and GitLab (repos) are all queried with public, key-free JSON APIs
in one parallel pass. A dead / rate-limited source is dropped and the rest
still deliver. Items use the same shape as find_all._app so they merge
cleanly into the Find ALL result and the repo-zip delivery path (package
items fall back to link-only at delivery time — see _send_repo_zip).

Probed key-free from this host (2026-11-04): all four return 200 JSON.
SourceForge and libraries.io are bot-walled (403/404 to non-browser UAs).
"""
import concurrent.futures

import requests

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def _head(extra=None):
    h = {"User-Agent": USER_AGENT}
    if extra:
        h.update(extra)
    return h


class Client:
    """Small requests wrapper so every source shares UA + timeout + error
    handling and so tests can inject one fake client for all sources."""

    def __init__(self, client=requests, timeout=(5, 20)):
        self.client = client
        self.timeout = timeout

    def get(self, url, headers=None, params=None):
        h = _head(headers)
        r = self.client.get(url, headers=h, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r


def _gh_url(it):
    name = it.get("name")
    if not name:
        return None
    return "https://www.npmjs.com/package/" + name


def _parse_npm(res):
    out = []
    for o in res.get("objects", []):
        p = o.get("package") or {}
        url = _gh_url(p)
        if not url:
            continue
        out.append({"id": p["name"], "url": url,
                    "desc": (p.get("description") or "").strip(),
                    "count": (o.get("downloads") or {}).get("monthly") or 0})
    return out


def _cr_url(c):
    repo = c.get("repository_url") or c.get("homepage") or \
        "https://crates.io/crates/" + c.get("name", "")
    return repo


def _parse_crates(res):
    out = []
    for c in res.get("crates", []):
        name = c.get("name")
        # floor: drop near-dead crates — fuzzy `q=` matching is loose, so
        # low-download hits are usually off-topic noise
        if not name or (c.get("downloads") or 0) < 1000:
            continue
        out.append({"id": name, "url": _cr_url(c),
                    "desc": (c.get("description") or "").strip(),
                    "count": c.get("downloads") or 0})
    return out


def _parse_docker(res):
    out = []
    for r in res.get("results", []):
        name = r.get("repo_name")
        if not name:
            continue
        out.append({"id": name, "url": "https://hub.docker.com/r/" + name,
                    "desc": (r.get("short_description") or "").strip(),
                    "count": r.get("pull_count") or 0})
    return out


def _parse_gitlab(res):
    out = []
    for p in res:
        path = p.get("path_with_namespace")
        # floor: zero-star + deletion-scheduled GitLab hits are noise
        if not path or (p.get("star_count") or 0) < 1 or "deletion" in path.lower():
            continue
        out.append({"id": path,
                    "url": p.get("web_url") or "https://gitlab.com/" + path,
                    "desc": (p.get("description") or "").strip(),
                    "count": p.get("star_count") or 0})
    return out


# (key, endpoint, url-params, extra-headers, parser, item-id)
_SOURCES = [
    ("npm", "https://registry.npmjs.org/-/v1/search",
     lambda q: {"text": q, "size": "8", "sort": "downloads"},
     {"accept": "application/vnd.npm.install-v1+json"}, _parse_npm, "name"),
    ("crates", "https://crates.io/api/v1/crates",
     lambda q: {"q": q, "per_page": "8"}, None, _parse_crates, "name"),
    ("docker", "https://hub.docker.com/v2/search/repositories/",
     lambda q: {"query": q, "page_size": "8"}, None, _parse_docker, "repo_name"),
    ("gitlab", "https://gitlab.com/api/v4/projects",
     lambda q: {"search": q, "per_page": "8", "order_by": "star_count",
                "sort": "desc"}, None, _parse_gitlab, "path_with_namespace"),
]


def _one_source(spec, q, limit, client):
    _key, endpoint, params, headers, parser, idk = spec
    try:
        res = client.get(endpoint, headers=headers, params=params(q)).json()
    except Exception:
        return []
    items = parser(res)
    out, seen = [], set()
    for it in items:
        ident = str(it.get(idk) or it.get("id"))
        if not ident or ident in seen:
            continue
        seen.add(ident)
        out.append({"source": _key, "id": ident,
                    "title": ident, "url": it.get("url", ""),
                    "desc": it.get("desc", ""), "count": it.get("count", 0)})
        if len(out) >= limit:
            break
    return out


def gather_global(query, limit=4, *, client=requests, timeout=(5, 20),
                  max_workers=6):
    """Query npm + crates + docker + gitlab in parallel for a topic.

    Returns {source_key: [item, ...]} (only non-empty sources). Any single
    source failing is dropped (fail-open); all dead -> {}. Offline-safe: a
    fake client injected in tests drives every source."""
    if not query or not query.strip():
        return {}
    q = query.strip()[:80]
    cl = client if isinstance(client, Client) else Client(client, timeout)
    out = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_one_source, spec, q, limit, cl): spec[0]
                for spec in _SOURCES}
        for fut in concurrent.futures.as_completed(futs):
            key = futs[fut]
            try:
                items = fut.result()
            except Exception:
                items = []
            if items:
                out[key] = items
    return out


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(gather_global(sys.argv[1] if len(sys.argv) > 1
                                   else "web automation"),
                     indent=2, ensure_ascii=False)[:2000])
