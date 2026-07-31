
## Build & Run

```bash
cd code2doc/app/agents/subagents/template_subagent/

# First time only: create your .env from the template
cp .env.example .env

docker build -t my_agent .

docker run -d \
  --name code_analyzer \
  -p 8007:8007 \
  --add-host=host.docker.internal:host-gateway \
  --env-file ./.env \
  -v "$(pwd):/app" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  code_analyzer
```

Replace `my_agent` with your agent's actual name throughout, and adjust the
port (`-p`) if your `config.yaml` / `.env` specifies a different one.