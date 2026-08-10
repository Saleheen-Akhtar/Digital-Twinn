#!/usr/bin/env python3
"""Re-upload out/ to the v2 bucket with correct keys (no shell arg mangling)."""
import os
import subprocess
import sys

BUCKET = "dtfm-frontend-976193237456-v2"
ROOT = r"C:\Users\sahil\AppData\Local\Temp\dtfm-check\apps\web\out"
REGION = "us-east-1"
PROFILE = "akshay"

TYPES = {
    ".html": "text/html",
    ".js": "application/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain",
    ".woff2": "font/woff2",
}

def content_type(path):
    return TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")

def upload(rel):
    full = os.path.join(ROOT, *rel.split("/"))
    ctype = content_type(full)
    cc = "public, max-age=31536000, immutable" if rel.startswith("_next/static/") else "public, max-age=0, must-revalidate"
    cmd = [
        "aws", "s3api", "put-object",
        "--bucket", BUCKET, "--key", rel, "--body", full,
        "--content-type", ctype, "--cache-control", cc,
        "--profile", PROFILE, "--region", REGION, "--output", "text",
    ]
    for attempt in range(1, 6):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            return True
    print("FAIL:", rel, r.stderr.strip()[:160], file=sys.stderr)
    return False

files = []
for dirpath, _dirs, names in os.walk(ROOT):
    for n in names:
        rel = os.path.relpath(os.path.join(dirpath, n), ROOT).replace("\\", "/")
        files.append(rel)

ok = sum(1 for f in files if upload(f))
print(f"uploaded={ok} total={len(files)}")
sys.exit(0 if ok == len(files) else 1)