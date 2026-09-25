import os

# Settings are read at import time by the app, so set the test environment first.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_DIR", "")
os.environ.setdefault("AI_ENABLED", "false")
