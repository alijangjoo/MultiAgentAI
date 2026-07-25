"""Run the AgentFramework API server from the project root."""

from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        app_dir="src",
        host="127.0.0.1",
        port=8080,
        reload=True,
    )
