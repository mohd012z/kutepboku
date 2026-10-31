"""Staging bridge guard: intentionally refuses to process live jobs."""
import os
from urllib.parse import urlsplit

def validate_worker_origin(value):
    if not isinstance(value, str):
        raise ValueError("Worker origin required")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.port is not None or parsed.path
            or parsed.query or parsed.fragment or value.endswith("/")):
        raise ValueError("Expected bare HTTPS origin")
    return value

def main():
    origin = os.getenv("CLOUDFLARE_WORKER_URL", "")
    validate_worker_origin(origin)
    raise SystemExit("Staging bridge disabled: integrate authenticated D1 job handling first")

if __name__ == "__main__":
    main()
