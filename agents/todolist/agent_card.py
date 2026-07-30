from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from prompts import build_orchestrator_description


GENERATE_BLOG_TODOS = AgentSkill(
    id="generate_blog_todos",
    name="Generate Blog Post Todo List",
    description=(
        "Generate a structured, step-by-step todo list for writing a blog post. "
        "Breaks a blog topic into actionable tasks such as research, outlining, "
        "drafting, fact-checking, adding media, SEO optimization, and final review."
    ),
    tags=[
        "blog",
        "writing",
        "todo",
        "planning",
        "content",
        "article",
        "seo",
    ],
    examples=[
        "Create a todo list for writing a blog about AI agents",
        "Plan the steps for a Python tutorial blog post",
        "Generate tasks for writing an SEO blog",
        "Break down a technical article into todos",
    ],
)


def build_agent_card(base_url: str) -> AgentCard:
    return AgentCard(
        name="Todo",
        description=build_orchestrator_description(),
        url=base_url.rstrip("/") + "/",
        version="1.0.0",
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities=AgentCapabilities(),
        skills=[GENERATE_BLOG_TODOS],
    )