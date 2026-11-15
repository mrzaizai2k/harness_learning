"""Shared settings for the backend. Values marked (env) can be overridden in .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent  # copied into each sandbox (AGENTS.md, skills/)

load_dotenv(PROJECT_ROOT / ".env")

MODEL_NAME = "gpt-5.4"

# Checkpointer files (see json_saver.py)
MEMORY_DIR = PROJECT_ROOT / "memory"
MEMORY_DIR.mkdir(exist_ok=True)
STATE_PATH = str(MEMORY_DIR / "state.json")
MEMORY_PATH = str(MEMORY_DIR / "memory.json")

# Files the host-side tools write (download_image)
OUTPUT_DIR = PROJECT_ROOT / "output"

# Subagents: local ones (YAML) and remote A2A ones (JSON, env)
SUBAGENTS_YAML = BACKEND_DIR / "subagents.yaml"
AGENT_LIST_PATH = os.getenv("AGENT_LIST_PATH", str(BACKEND_DIR / "agent_list.json"))

# Folders the UI lists as agent output
CONTENT_DIRS = ("blogs", "research", "output", "linkedin", "tweets")

# Per-thread Docker sandbox
SANDBOX_RUNTIME = "python-minimal"
SANDBOX_WORKDIR = "/workspace"

# Frontend origins allowed to call the API (env, comma-separated)
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]

# Langfuse tracing is on only when its keys are set (env)
LANGFUSE_ENABLED = bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))
