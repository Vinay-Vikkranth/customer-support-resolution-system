import os
import tempfile
from pathlib import Path

TEST_DIR = tempfile.TemporaryDirectory(prefix="resolvedesk-tests-")
os.environ["RESOLVEDESK_DB"] = str(Path(TEST_DIR.name) / "test.db")
os.environ["RESOLVEDESK_TOKEN"] = "test-operator"
os.environ["RESOLVEDESK_REVIEW_TOKEN"] = "test-reviewer"
# Explicit blanks override any real credentials in the developer's ignored .env.
# Removing a variable would allow app.config.load_env() to re-enable paid calls.
os.environ["OPENAI_API_KEY"] = ""
os.environ["ACCOUNT_API_URL"] = ""
os.environ["RESOLVEDESK_DISABLE_TOKENS"] = "0"
