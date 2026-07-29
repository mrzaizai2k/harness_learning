DESCRIPTION = """This agent generates structured todo lists for writing blog posts.
It breaks a blog topic into clear, actionable tasks such as researching the topic,
collecting credible sources, creating an outline, drafting sections, fact-checking,
adding images and videos, optimizing for SEO, proofreading, and preparing the post
for publication. The agent returns an ordered todo list that guides the entire blog
writing process from planning to completion."""


def build_orchestrator_description() -> str:
    return f"DESCRIPTION: {DESCRIPTION}"