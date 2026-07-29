---
name: social-media
description: >-
  Create complete social media content from research to final evaluation.
  Supports LinkedIn and Twitter/X with task planning, research, platform-
  specific content generation, companion images, YouTube recommendations,
  hashtags, optional publishing schedules, and quality evaluation. Use for
  LinkedIn posts, tweets, Twitter/X threads, social media captions, or other
  platform-specific social content.
---

# Social Media Content Skill

This skill produces complete social media content, from planning to final quality evaluation.

## Workflow

Execute the following steps **in order**.

---

## 1. Generate a Social Media Task List

Always begin by asking the **todo** subagent to generate a detailed implementation plan.

**Do not call the `write_todos` tool directly.**

```python
task(
    subagent_type="todo",
    description="Generate a detailed task list for creating <platform> content about <topic>."
)
```

The generated task list should cover every major stage required to produce the requested social media content.

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
- Base the content on the collected research.
- Use the gathered facts and sources where appropriate.
- Avoid unsupported claims.

---

## 3. Create the Output Directory

### LinkedIn

Store all outputs under:

```text
linkedin/<slug>/
```

Required:

```text
linkedin/<slug>/
    post.md
    image.png
```

Optional:

```text
linkedin/<slug>/
    schedule.json
```

---

### Twitter / X

Store all outputs under:

```text
tweets/<slug>/
```

Required:

```text
tweets/<slug>/
    thread.md
    image.png
```

Optional:

```text
tweets/<slug>/
    schedule.json
```

---

## 4. Write the Content

### LinkedIn

Save the post to:

```text
linkedin/<slug>/post.md
```

Guidelines:

- Strong opening hook
- Professional yet conversational tone
- Short, readable paragraphs
- Actionable insights
- Clear call to action
- 3–5 relevant hashtags
- Approximately 1,300 characters or fewer

Suggested structure:

```text
Hook

Context

Main insight

Call to action

#hashtags
```

---

### Twitter / X

Save the thread to:

```text
tweets/<slug>/thread.md
```

Guidelines:

- Strong opening tweet
- Short and engaging tweets
- Number tweets when appropriate
- End with a takeaway or call to action
- Optimize for readability and engagement

---

## 5. Generate the Companion Image

Every social media post must include a companion image.

Generate or download a relevant image and save it as:

LinkedIn:

```text
linkedin/<slug>/image.png
```

Twitter/X:

```text
tweets/<slug>/image.png
```

For implementation details, refer to:

```text
reference/extract-image.md
```

A social media post is **not complete** until its image has been generated.

---

## 6. Recommend a YouTube Video

Always obtain **one relevant YouTube video** by running the infotainment agent **inside the sandbox**.

```bash
execute(python call_infotainment_agent.py --task "<topic>")
```

The command returns:

- Video title
- Video URL

Include both in a **Recommended Video** section within the generated content.

---

## 7. Schedule Publishing (Optional)

Only perform this step if the user explicitly requests scheduling or automatic publishing.

Run the scheduler **inside the sandbox**.

For LinkedIn:

```bash
execute(python schedule.py --dir linkedin/<slug>)
```

For Twitter/X:

```bash
execute(python schedule.py --dir tweets/<slug>)
```

This generates:

```text
schedule.json
```

Scheduling must occur **after**:

1. Research
2. Content generation
3. Companion image generation
4. YouTube recommendation

---

## 8. Evaluate the Content

Always perform a final quality review before considering the task complete.

Delegate evaluation to the **evaluator** subagent.

```python
task(
    subagent_type="evaluator",
    description="Evaluate the generated social media content in <platform>/<slug>. Return a score and improvement suggestions."
)
```

The evaluator should report:

- Overall score (0–10)
- PASS if score > 5
- FAIL if score ≤ 5
- Reasoning
- Checklist of evaluated criteria
- Improvement suggestions (if needed)

### Evaluation Criteria

Verify that:

- The post or thread exists.
- The content matches the requested platform.
- The content reflects the research findings.
- The companion image exists.
- A valid YouTube recommendation is included.
- Hashtags are included where appropriate.
- The formatting is clear and engaging.

### Mandatory Failure Conditions

The evaluation **must FAIL**, regardless of score, if any required output is missing:

- `post.md` (LinkedIn) or `thread.md` (Twitter/X)
- `image.png`
- A YouTube recommendation (title and URL)

If evaluation fails, the report should clearly explain what is missing and recommend concrete actions, such as:

- Generate the companion image.
- Add a YouTube recommendation.
- Improve the opening hook.
- Improve platform-specific formatting.
- Strengthen the call to action.
- Rewrite weak content.
- Regenerate missing files.

---

## Expected Outputs

### LinkedIn

Required:

```text
linkedin/<slug>/
    post.md
    image.png
```

Optional:

```text
linkedin/<slug>/
    schedule.json
```

---

### Twitter / X

Required:

```text
tweets/<slug>/
    thread.md
    image.png
```

Optional:

```text
tweets/<slug>/
    schedule.json
```

---

## Completion Checklist

Before completing the task, verify that:

- ✓ Todo list generated
- ✓ Research completed
- ✓ Content created and saved
- ✓ Companion image generated
- ✓ YouTube recommendation included
- ✓ Hashtags included where appropriate
- ✓ Publishing schedule created (if requested)
- ✓ Evaluation completed
- ✓ Final evaluation result is PASS