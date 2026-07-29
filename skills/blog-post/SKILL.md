---
name: blog-post
description: >-
  Create complete long-form blog posts from research to final evaluation.
  Includes task planning, research, article writing, hero image generation,
  YouTube recommendations, hashtags, optional publishing schedules, and
  quality evaluation. Use for blog posts, articles, tutorials, technical
  guides, documentation, thought leadership, or other SEO-focused long-form
  content.
---

# Blog Post Skill

This skill produces a complete blog post workflow, from planning to final quality evaluation.

## Workflow

Execute the following steps **in order**.

---

## 1. Generate a Blog Task List

Always begin by asking the **todo** subagent to generate a detailed implementation plan. DO not using write_todos tool directly. The task list should cover all major stages required to produce the blog post.

```python
task(
    subagent_type="todo",
    description="Generate a detailed task list for writing a blog post about <topic>."
)
```

This task list should cover all major stages required to produce the blog.

---

## 2. Research the Topic

Use the **researcher** subagent to gather information.

```python
task(
    subagent_type="researcher",
    description="Research <topic>. Save findings to research/<slug>.md"
)
```

After the researcher completes:

- Read `research/<slug>.md`.
- Base the article on the collected research.
- Cite or reference the gathered sources where appropriate.
- Avoid making unsupported claims.

---

## 3. Create the Blog Directory

Store all generated files under:

```text
blogs/<slug>/
```

Required files:

```text
blogs/<slug>/
    post.md
    hero.png
```

Optional (only if publishing is requested):

```text
blogs/<slug>/
    schedule.json
```

---

## 4. Write the Blog Post

Save the article as:

```text
blogs/<slug>/post.md
```

The article should include:

1. Title
2. Introduction (hook)
3. Background or context
4. 3–5 main sections
5. Practical examples or applications
6. Conclusion
7. Recommended YouTube Video

Writing guidelines:

- Write for readers first and SEO second.
- Base all factual content on the research results.
- Include examples where helpful.
- Include code snippets for technical topics.
- Use clear headings and bullet lists.
- Avoid repetition.
- Maintain a clear, engaging writing style.

---

## 5. Generate the Hero Image

Create a cover image that represents the article.

Save it as:

```text
blogs/<slug>/hero.png
```

Also generate promotional hashtags using the `generate_hashtags` tool.

---

## 6. Recommend a YouTube Video

Always obtain **one relevant YouTube video** by running the infotainment agent **inside the sandbox**.

```bash
execute(python call_infotainment_agent.py --task "<blog topic>")
```

The command returns:

- Video title
- Video URL

Include both in the **Recommended Video** section near the end of the article.

---

## 7. Schedule Publishing (Optional)

Only perform this step if the user explicitly requests scheduling or automatic publishing.

Run the scheduler **inside the sandbox**.

```bash
execute(python schedule.py --dir blogs/<slug>)
```

This generates:

```text
blogs/<slug>/schedule.json
```

Scheduling must occur **after**:

1. Research
2. Blog writing
3. Hero image generation

---

## 8. Evaluate the Blog

Always perform a final quality review before considering the task complete.

Delegate evaluation to the **evaluator** subagent.

```python
task(
    subagent_type="evaluator",
    description="Evaluate the generated blog in blogs/<slug>. Return a score and improvement suggestions."
)
```

The evaluator should report:

- Overall score (0–10)
- PASS if score > 5
- FAIL if score ≤ 5
- Reasoning
- Checklist of evaluated criteria
- Improvement suggestions (if needed)

### Mandatory Failure Conditions

The evaluation **must FAIL**, regardless of score, if any required output is missing:

- `blogs/<slug>/post.md`
- `blogs/<slug>/hero.png`
- A YouTube recommendation (title and URL)

If evaluation fails, the report should clearly explain what is missing and recommend concrete actions, such as:

- Generate the hero image.
- Add a YouTube recommendation.
- Improve research coverage.
- Expand incomplete sections.
- Fix formatting or structure.
- Regenerate missing files.

---

## Expected Outputs

Required:

```text
blogs/<slug>/
    post.md
    hero.png
```

Optional:

```text
blogs/<slug>/
    schedule.json
```

---

## Completion Checklist

Before completing the task, verify that:

- ✓ Todo list generated
- ✓ Research completed
- ✓ `post.md` created
- ✓ `hero.png` created
- ✓ YouTube recommendation included
- ✓ Hashtags generated
- ✓ Publishing schedule created (if requested)
- ✓ Evaluation completed
- ✓ Final evaluation result is PASS