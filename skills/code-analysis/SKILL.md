---
name: code-analysis
description: >-
  Analyze and understand a source code repository. 
---

# Code Analysis

Always call Agent to analyze code, DO not use the general tool directly. The agent will handle the analysis and provide a structured response.


```python
task(
    subagent_type="CodeAnalyzer",
    description="Analyze this code <path to source code base> for me."
)
```
