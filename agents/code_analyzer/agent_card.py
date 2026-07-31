"""A2A card for the Code2Graph agent."""

from __future__ import annotations

from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from prompts import build_orchestrator_description


CODE2GRAPH_SKILL = AgentSkill(
    id="query_cpp_code_graph",
    name="Query C/C++ Code Graph",
    description=(
        "Index a C/C++ source tree and query symbols, definitions, uses, callers, "
        "callees, and include relationships with exact source locators."
    ),
    tags=["c", "cpp", "code-analysis", "code-graph", "call-graph", "symbols"],
    examples=[
        "Search for symbol Can_Init",
        "Who calls Can_Write?",
        "Explain the Can_ConfigType type",
        "Return the complete graph as JSON",
    ],
)


def build_agent_card(base_url: str) -> AgentCard:
    return AgentCard(
        name="Code Analyzer",
        description=build_orchestrator_description(),
        url=base_url.rstrip("/") + "/",
        version="1.0.0",
        defaultInputModes=["text", "application/json"],
        defaultOutputModes=["text", "application/json", "image/svg+xml"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[CODE2GRAPH_SKILL],
    )
