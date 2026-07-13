from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_openai import ChatOpenAI

model = ChatOpenAI(model="gpt-4.1-mini")

agent = create_deep_agent(
    model=model,
    backend=FilesystemBackend(root_dir="."),  # points at your real project folder
)

if __name__ == "__main__":
    result = agent.invoke({
        "messages": [{"role": "user", "content": "Edit file README.md and say that this is a project to learn harness"}]
    })
    print(result["messages"][-1].content)