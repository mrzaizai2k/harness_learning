docker build -t todo_agent agents/todolist

docker run -d \
  --name todo_agent \
  -p 8005:8005 \
  --add-host=host.docker.internal:host-gateway \
  --env-file ./.env \
  -v "$(pwd)/agents/todolist:/app" \
  todo_agent