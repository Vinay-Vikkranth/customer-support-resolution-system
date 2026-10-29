"""Local launcher: credentials are generated per process unless supplied via environment."""

import sys
from pathlib import Path

deps = Path(__file__).parent / ".deps"
if deps.exists():
    sys.path.insert(0, str(deps))
if __name__ == "__main__":
    import uvicorn
    from app.main import app, TOKEN, REVIEW_TOKEN

    print(
        "\nResolveDesk: http://127.0.0.1:8000\nOperator token:",
        TOKEN,
        "\nReviewer token:",
        REVIEW_TOKEN,
        flush=True,
    )
    uvicorn.run(app, host="127.0.0.1", port=8000)
