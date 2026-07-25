---
name: schedule-post
description: Schedules previously generated blog posts or social media content for publishing. Use when the user asks to schedule, queue, publish later, auto-post, or plan publishing of existing content.
---
# Schedule Post Skill

## Purpose

This skill schedules content that has already been created.

Supported content:

- Blog posts
- LinkedIn posts
- Twitter/X threads

The content must already exist on disk before scheduling.

---

# Prerequisites

Before scheduling, verify that the target directory exists.

Supported directories include:

```text
blogs/<slug>/
linkedin/<slug>/
tweets/<slug>/
```

Examples:

```text
blogs/ai-agents-2025/
linkedin/prompt-engineering/
tweets/llm-tips/
```

The directory should already contain the generated content, for example:

```text
blogs/<slug>/
├── post.md
└── hero.png
```

or

```text
linkedin/<slug>/
├── post.md
└── image.png
```

or

```text
tweets/<slug>/
├── thread.md
└── image.png
```

If the directory does not exist, inform the user that the content must be created first.

---

# Schedule the Post

Run the scheduling CLI **inside the sandbox**.

Command:

```bash
python schedule.py --dir <content-directory>
```

Examples:

```bash
python schedule.py --dir blogs/ai-agents-2025
```

```bash
python schedule.py --dir linkedin/prompt-engineering
```

```bash
python schedule.py --dir tweets/llm-tips
```

Always execute the command inside the sandbox environment.

---

# Expected Result

The scheduling tool will generate the publishing metadata (for example `schedule.json`, depending on the scheduler implementation).

Do not modify the generated files.

---

# Workflow

```text
Locate existing content
        ↓
Verify directory exists
        ↓
Run:

python schedule.py --dir <directory>

        ↓
Confirm scheduling completed
```

---

# Error Handling

If scheduling fails:

1. Report the CLI error.
2. Do not attempt to modify the content.
3. Do not rerun with a different directory unless requested.

If the target directory does not exist:

- Explain that the content has not been generated yet.
- Ask the user to create the content first.

---

# Quality Checklist

Before finishing:

- [ ] Target directory exists
- [ ] Scheduling command executed inside the sandbox
- [ ] Scheduling completed successfully
- [ ] Any scheduler output preserved