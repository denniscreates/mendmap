"""MendMap backend. Settings come from the environment, or from backend/.env if it exists."""
from pathlib import Path

try:
    from dotenv import load_dotenv

    # Values already set in the environment (e.g. by the tests) win over the file.
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:  # python-dotenv comes with uvicorn[standard]; without it, use real env vars
    pass
