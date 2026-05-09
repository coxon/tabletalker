"""Quick smoke test: POST to /v1/batch with the quick manifest + 3 files.
Run from repo root:  cd src/backend && uv run python ../../eval/batch-test/test_upload.py
"""
import httpx, sys, pathlib

BASE = pathlib.Path(__file__).resolve().parent
manifest = BASE / "manifest-quick.jsonl"
data_files = [
    BASE / "01_ibm_attrition.csv",
    BASE / "02_superstore_sales.csv",
    BASE / "05_shopping_behavior.csv",
]

files_payload = [("manifest", (manifest.name, manifest.open("rb"), "application/octet-stream"))]
for f in data_files:
    files_payload.append(("files", (f.name, f.open("rb"), "text/csv")))

print(f"Uploading manifest + {len(data_files)} data files...")
try:
    r = httpx.post("http://127.0.0.1:8000/v1/batch", files=files_payload, timeout=600)
    print(f"Status: {r.status_code}")
    print(f"X-Batch-Tasks: {r.headers.get('x-batch-tasks')}")
    print(f"X-Batch-Errors: {r.headers.get('x-batch-errors')}")
    if r.status_code == 200:
        out = BASE / "result.xlsx"
        out.write_bytes(r.content)
        print(f"Saved {out} ({len(r.content)} bytes)")
    else:
        print(r.text[:500])
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
