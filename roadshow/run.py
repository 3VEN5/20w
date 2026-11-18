"""Run locally: python roadshow/run.py --demo [--port 8765]."""
import argparse
import os
import sys
import tempfile
from pathlib import Path

here = Path(__file__).resolve().parent
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--demo", action="store_true")
    p.add_argument("--port", type=int, default=8765)
    opts = p.parse_args()
    os.environ["ROADSHOW_DEMO"] = "1" if opts.demo else "0"
    sandbox = tempfile.TemporaryDirectory(prefix="20w-fiction-") if opts.demo else None
    os.environ["APP_DB"] = str(Path(sandbox.name) / "fiction.db") if sandbox else os.environ.get("APP_DB", str(here / "data" / "app.db"))
    os.environ["SECURE_COOKIE"] = "0"
    sys.path.insert(1, str(here.parent / "app"))
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=opts.port)
