"""Objects shared by every route: one model client, one checkpointer, one runner pool."""

from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI

from backend import config
from backend.agent_runner import RunnerPool
from backend.json_saver import JsonFileSaver

model = ChatOpenAI(model=config.MODEL_NAME)  # reads OPENAI_API_KEY from env
checkpointer = JsonFileSaver(state_path=config.STATE_PATH, memory_path=config.MEMORY_PATH)
pool = RunnerPool(model, checkpointer)

# A container-free graph used only to *read* past threads. Reading through a
# compiled graph (not the raw checkpoint) matters: LangGraph stores `messages`
# as a delta channel that only the graph can rebuild.
history_reader = create_deep_agent(model=model, checkpointer=checkpointer)
