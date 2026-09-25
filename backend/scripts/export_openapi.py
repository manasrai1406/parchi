"""Write the API's OpenAPI spec to a file, without starting a server.

Usage: uv run python scripts/export_openapi.py ../frontend/openapi.json
"""

import json
import sys
from pathlib import Path

from parchi.api.main import app

if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    target.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {target}")
