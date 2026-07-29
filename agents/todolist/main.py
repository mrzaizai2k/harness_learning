import os
from urllib.parse import urlparse

import uvicorn

from agent_card import build_agent_card
from agent_executor import TodoAgentExecutor

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore


# ==================================================
# Configuration
# ==================================================

BASE_URL = os.environ.get(
    "TODO_AGENT_BASE_URL",
    "http://localhost:8005",
)

# Extract port from URL
parsed_url = urlparse(BASE_URL)

PORT = parsed_url.port or 8005


# ==================================================
# Initialize executor
# ==================================================

executor = TodoAgentExecutor()

# Optional warm-up
# executor.warm_up()


# ==================================================
# Build agent card
# ==================================================

agent_card = build_agent_card(BASE_URL)


# ==================================================
# Build A2A application
# ==================================================

request_handler = DefaultRequestHandler(
    agent_executor=executor,
    task_store=InMemoryTaskStore(),
)

app_builder = A2AStarletteApplication(
    agent_card=agent_card,
    http_handler=request_handler,
)

app = app_builder.build()


# ==================================================
# Main
# ==================================================

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
    )