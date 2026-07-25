---
name: blog-post
description: >-
  Research, write, evaluate, and publish long-form blog posts with SEO
  structure, hero image generation, YouTube recommendations, hashtags,
  quality evaluation, and optional publishing schedules. Use when the user
  asks for blog posts, articles, tutorials, technical guides,
  documentation, thought leadership content, or long-form SEO content.
---

# Blog Post Skill

This skill creates complete long-form blog content from research through final quality evaluation and publishing assets.

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

- Read `research/<slug>.md`
- Base the article on those findings.
- Use the collected sources throughout the article.

---

## 2. Create the blog directory

All outputs belong inside:

```text
blogs/<slug>/
```

Required structure:

```text
blogs/<slug>/
    post.md
    hero.png
```

Optional:

```text
schedule.json
```

when publishing is requested.

---

## 3. Write the article

Save the article to:

```text
blogs/<slug>/post.md
```

Every article should contain:

1. Hook
2. Context
3. 3–5 major sections
4. Practical application
5. Conclusion
6. Recommended Video

Guidelines:

- Write for humans first, SEO second.
- Base claims on the research findings.
- Include practical examples.
- Include code snippets when appropriate.
- Use headings and bullet lists where useful.
- Avoid unnecessary repetition.
- Maintain a clear and engaging writing style.

---

## 4. Generate the hero image

Generate a cover image that represents the article.

Save it as:

```text
blogs/<slug>/hero.png
```

Also generate hashtags using the `generate_hashtags` tool for future promotion.

---

## 5. Recommend a YouTube video

Always obtain one relevant YouTube video by running **inside the sandbox**.

```bash
execute(python call_infotainment_agent.py --task "<blog topic>")
```

The command returns a video title and URL.

Include both in a **Recommended Video** section near the end of the article.

---

## 6. Schedule publishing (Optional)

Only perform this step if the user explicitly requests scheduling or automatic publishing.

Run **inside the sandbox**:

```bash
execute(python schedule.py --dir blogs/<slug>)
```

This generates publishing metadata such as:

```text
blogs/<slug>/schedule.json
```

Scheduling should always happen **after**:

1. Research
2. Article generation
3. Hero image generation

---

## 7. Evaluate the final output

Always perform a final quality review before considering the task complete.

Delegate to the evaluator.

```python
task(
    subagent_type="evaluator",
    description="Evaluate the blog output in blogs/<slug>. Return a score and improvement suggestions."
)
```

The evaluator must inspect the generated output and return:

- Overall score (0–10)
- PASS if score > 5
- FAIL if score ≤ 5
- Reason for the score
- Detailed checklist
- Next steps if improvements are required

### Automatic Failure Conditions

The evaluation must FAIL regardless of score if:

- `hero.png` is missing.
- No YouTube URL is present.
- `post.md` is missing.

When the evaluation fails, the evaluator should explain exactly what is missing and recommend concrete next steps, such as:

- Generate the hero image.
- Add a YouTube recommendation.
- Improve research coverage.
- Expand incomplete sections.
- Fix formatting or structure.
- Regenerate missing files.

---

## Expected Output

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

Before finishing, verify:

- ✓ Research completed
- ✓ `post.md` written
- ✓ `hero.png` generated
- ✓ Recommended YouTube video included
- ✓ Hashtags generated
- ✓ Scheduling completed (if requested)
- ✓ Evaluator executed
- ✓ Evaluation result is PASS
- ✓ If evaluation failed, required improvements have been identified
