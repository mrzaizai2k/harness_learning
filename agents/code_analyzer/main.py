"""Entry point for the Code2Graph A2A agent."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from agent_card import build_agent_card
from agent_executor import Code2GraphAgentExecutor


# ==================================================
# Configuration
# ==================================================

BASE_URL = os.environ.get(
    "CODE_ANALYZER_BASE_URL",
    "http://localhost:8999",
)

parsed_url = urlparse(BASE_URL)

_DEFAULT_PORTS = {
    "http": 80,
    "https": 443,
}

if parsed_url.port:
    PORT = parsed_url.port
elif os.environ.get("CODE_ANALYZER_LISTEN_PORT"):
    PORT = int(os.environ["CODE_ANALYZER_LISTEN_PORT"])
else:
    PORT = _DEFAULT_PORTS.get(parsed_url.scheme, 8999)


# ==================================================
# Initialize executor
# ==================================================

executor = Code2GraphAgentExecutor()

# Optional warm-up
# executor.run("health check")


# ==================================================
# Build Agent Card
# ==================================================

agent_card = build_agent_card(BASE_URL)


# ==================================================
# Build A2A Application
# ==================================================

request_handler = DefaultRequestHandler(
    agent_executor=executor,
    task_store=InMemoryTaskStore(),
)

app = A2AStarletteApplication(
    agent_card=agent_card,
    http_handler=request_handler,
).build()


# ==================================================
# Main
# ==================================================

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
    )