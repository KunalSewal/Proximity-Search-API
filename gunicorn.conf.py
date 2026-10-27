"""gunicorn settings, read from the environment (loaded automatically from the working dir)."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WORKERS", 4))
threads = int(os.environ.get("THREADS", 2))
timeout = 120
accesslog = "-"
errorlog = "-"
