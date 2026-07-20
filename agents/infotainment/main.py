import os
from urllib.parse import urlparse

from agent_card import build_agent_card
from agent_executor import InfotainmentAgentExecutor

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore


import uvicorn


# ==================================================
# Configuration
# ==================================================

BASE_URL = os.environ.get(
    "INFOTAINMENT_BASE_URL",
    "http://infotainment:8004",
)

# Extract port from BASE_URL
parsed_url = urlparse(BASE_URL)

PORT = parsed_url.port or 8004


# ==================================================
# Build agent card
# ==================================================

agent_card = build_agent_card(BASE_URL)


# ==================================================
# Request handler
# ==================================================

request_handler = DefaultRequestHandler(
    agent_executor=InfotainmentAgentExecutor(),
    task_store=InMemoryTaskStore(),
)


# ==================================================
# Build A2A app
# ==================================================

app_builder = A2AStarletteApplication(
    agent_card=agent_card,
    http_handler=request_handler,
)

app = app_builder.build()


# ==================================================
# Main
# ==================================================

if __name__ == "__main__":

    print(f"Starting Infotainment Agent at {BASE_URL}")
    print(f"Detected port: {PORT}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
    )