import os
import tempfile
from pathlib import Path

TEST_DIR = tempfile.TemporaryDirectory(prefix="resolvedesk-tests-")
os.environ["RESOLVEDESK_DB"] = str(Path(TEST_DIR.name) / "test.db")
os.environ["RESOLVEDESK_TOKEN"] = "test-operator"
os.environ["RESOLVEDESK_REVIEW_TOKEN"] = "test-reviewer"
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("RESOLVEDESK_DISABLE_TOKENS", None)
