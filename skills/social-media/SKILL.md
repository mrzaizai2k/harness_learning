---
name: social-media
description: >-
  Research, create, evaluate, and optionally schedule engaging social media
  content for LinkedIn and Twitter/X. Generates platform-specific posts,
  companion images, YouTube recommendations, hashtags, quality evaluations,
  and publishing schedules. Use when the user asks to write a LinkedIn post,
  tweet, Twitter/X thread, social media caption, social post, or repurpose
  content for social platforms.
---

# Social Media Content Skill

This skill produces complete social media content from research through final quality evaluation.

## Workflow

Follow these steps in order.

---

## 1. Research

Always start by delegating research.

```python
task(
    subagent_type="researcher",
    description="Research <topic>. Save findings to research/<slug>.md"
)
```

After the researcher finishes:

- Read `research/<slug>.md`.
- Base the content on those findings.
- Use the collected facts and sources throughout the post.

---

## 2. Create the output directory

### LinkedIn

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
schedule.json
```

---

### Twitter / X

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
schedule.json
```

---

## 3. Write the content

### LinkedIn

Save to:

```text
linkedin/<slug>/post.md
```

Guidelines:

- Strong first-line hook
- Professional but conversational
- Short paragraphs
- Practical insight
- Clear call to action
- 3–5 hashtags
- Maximum approximately 1,300 characters

Recommended structure:

```text
Hook

Context

Main insight

Call to action

#hashtags
```

---

### Twitter / X

Save to:

```text
tweets/<slug>/thread.md
```

Guidelines:

- Strong opening tweet
- Concise tweets
- Number tweets when appropriate
- End with a takeaway or CTA
- Optimize for readability and engagement

---

## 4. Generate the companion image

Every social media post requires an image.

Generate or download an appropriate image and save it as:

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

A social media post is **not complete** without its image.

---

## 5. Recommend a YouTube video

Always obtain one relevant YouTube video by running **inside the sandbox**.

```bash
execute(python call_infotainment_agent.py --task "<topic>")
```

The command returns a video title and URL.

Include both in the generated content under a short **Recommended Video** section.

---

## 6. Schedule publishing (Optional)

Only execute this step if the user explicitly requests scheduling or automatic publishing.

Run **inside the sandbox**.

For LinkedIn:

```bash
execute(python schedule.py --dir linkedin/<slug>)
```

For Twitter/X:

```bash
execute(python schedule.py --dir tweets/<slug>)
```

This generates scheduling metadata such as:

```text
schedule.json
```

Scheduling should always happen **after**:

1. Research
2. Content generation
3. Image generation
4. YouTube recommendation

---

## 7. Evaluate the final output

Always perform a final quality review before considering the task complete.

Delegate to the evaluator.

```python
task(
    subagent_type="evaluator",
    description="Evaluate the social media output in <platform>/<slug>. Return a score and improvement suggestions."
)
```

The evaluator must inspect the generated output and return:

- Overall score (0–10)
- PASS if score > 5
- FAIL if score ≤ 5
- Reason for the score
- Detailed checklist
- Next steps if improvements are required

### Evaluation Requirements

The evaluator should verify:

- The post or thread exists.
- The content is engaging and appropriate for the platform.
- Research findings are reflected in the content.
- An accompanying image exists.
- A valid YouTube URL is included.
- Hashtags are included where appropriate.
- The content is well formatted.

### Automatic Failure Conditions

The evaluation must FAIL regardless of score if:

- `image.png` is missing.
- No YouTube URL is present.
- The post (`post.md`) or thread (`thread.md`) is missing.

When the evaluation fails, the evaluator should explain exactly what is missing and recommend concrete next steps, such as:

- Generate the companion image.
- Add a YouTube recommendation.
- Improve the hook.
- Improve platform-specific formatting.
- Strengthen the call to action.
- Expand or rewrite weak sections.
- Regenerate missing files.

---

## Expected Output

### LinkedIn

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

Before finishing, verify:

- ✓ Research completed
- ✓ Content written and saved
- ✓ Companion image generated
- ✓ Recommended YouTube video included
- ✓ Hashtags included where appropriate
- ✓ Scheduling completed (if requested)
- ✓ Evaluator executed
- ✓ Evaluation result is PASS
- ✓ If evaluation failed, required improvements have been identified
