"""Run the local Cursor Bridge (port 9090 by default)."""

import os
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

if __name__ == "__main__":
    port = int(os.environ.get("CURSOR_BRIDGE_PORT", "9090"))
    uvicorn.run(
        "cursor_bridge.server:app",
        app_dir="src",
        host="127.0.0.1",
        port=port,
        reload=False,
    )
