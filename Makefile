# Option B: run each piece yourself (backend + frontend on the host, agents in Docker).
# Option A (everything in Docker) is `make up`; see README.

ENV_FILE := $(CURDIR)/.env

.PHONY: install be fe agents agents-stop \
        agent-infotainment agent-todolist agent-code-analyzer \
        up down logs

install:
	uv sync
	cd frontend && npm install

be:
	uv run uvicorn backend.main:app --reload --port 8000

fe:
	cd frontend && npm run dev

# ---- A2A agents (each in its own container, reachable on localhost) ----
agent-infotainment:
	docker build -t infotainment_agent agents/infotainment
	docker rm -f infotainment_agent 2>/dev/null || true
	docker run -d --name infotainment_agent -p 8004:8004 \
		--env-file $(ENV_FILE) -e INFOTAINMENT_BASE_URL=http://localhost:8004 \
		-v $(CURDIR)/agents/infotainment:/app \
		infotainment_agent

agent-todolist:
	docker build -t todolist_agent agents/todolist
	docker rm -f todolist_agent 2>/dev/null || true
	docker run -d --name todolist_agent -p 8005:8005 \
		--env-file $(ENV_FILE) -e TODO_AGENT_BASE_URL=http://localhost:8005 \
		-v $(CURDIR)/agents/todolist:/app \
		todolist_agent

agent-code-analyzer:
	docker build -t code_analyzer_agent agents/code_analyzer
	docker rm -f code_analyzer_agent 2>/dev/null || true
	docker run -d --name code_analyzer_agent -p 8007:8007 \
		--env-file $(ENV_FILE) -e CODE_ANALYZER_BASE_URL=http://localhost:8007 \
		-v $(CURDIR)/agents/code_analyzer:/app \
		-v /var/run/docker.sock:/var/run/docker.sock \
		code_analyzer_agent

agents: agent-infotainment agent-todolist agent-code-analyzer

agents-stop:
	docker rm -f infotainment_agent todolist_agent code_analyzer_agent 2>/dev/null || true

# ---- Option A: Docker Compose shortcuts ----
up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f
