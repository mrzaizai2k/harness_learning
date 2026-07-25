---
name: youtube-video
description: Find a relevant YouTube video for a topic and extract its title and URL. Use when you want to recommend a YouTube video in a blog post, social media post, or other content.
---
# Find YouTube Video Skill

## Purpose

This skill finds a relevant YouTube video for a given topic and extracts its title and URL so it can be included as a recommended resource.

## When to Use

- **REQUIRED** when a blog post or social media post should recommend a YouTube video
- When users ask for related learning resources
- When you want to provide an external video reference

## Sandbox Execution

**All commands in this document are CLI commands that must be executed inside the sandbox environment.**

- Do **not** interpret these as Python code snippets.
- Do **not** execute them on the host machine.
- Run them exactly as shell commands within the sandbox terminal.
- The sandbox environment already contains the required scripts and dependencies.

## Tool Required

Execute the following CLI command **inside the sandbox**:

```bash
python call_infotainment_agent.py --task "<TOPIC>"
```

## Workflow

### Step 1: Find a Relevant Video

Execute the infotainment agent CLI command inside the sandbox with the desired topic.

Example:

```bash
python call_infotainment_agent.py --task "baby song"
```

Example response:

```json
{
  "success": true,
  "message": "Best of 2024 ⭐️ | Top Kids Songs from the Super Simple Universe! | Super Simple Songs",
  "data": {
    "url": "https://www.youtube.com/watch?v=KGhWfzjcdRM"
  }
}
```

### Step 2: Extract the Information

Extract the following fields from the response:

- **Title** ← `message`
- **URL** ← `data.url`

Example:

```
Title:
Best of 2024 ⭐️ | Top Kids Songs from the Super Simple Universe! | Super Simple Songs

URL:
https://www.youtube.com/watch?v=KGhWfzjcdRM
```

### Step 3: Add to the Content

Include the video as a recommended resource in the generated content.

Example Markdown:

```markdown
## Recommended Video

**Best of 2024 ⭐️ | Top Kids Songs from the Super Simple Universe! | Super Simple Songs**

https://www.youtube.com/watch?v=KGhWfzjcdRM
```

## Complete Example

The following demonstrates the complete workflow. The first line is a **CLI command executed inside the sandbox**, while the remaining lines show the expected response and how to consume it.

```text
# Execute inside the sandbox
python call_infotainment_agent.py --task "AI agents"

# Response
{
  "success": true,
  "message": "AI Agents Explained in 15 Minutes",
  "data": {
    "url": "https://www.youtube.com/watch?v=xxxxxxxxxxx"
  }
}

# Extract
title = response["message"]
url = response["data"]["url"]

# Include title and URL in the generated content
```

## Error Handling

If an error occurs:

- Verify that the sandbox command executed successfully.
- Check whether `success` is `true`.
- If no suitable video is found, omit the recommendation section.
- Do not fabricate a title or URL.

## Quality Checklist

Before considering this step complete:

- [ ] CLI command executed inside the sandbox
- [ ] Infotainment agent completed successfully
- [ ] Response has `"success": true`
- [ ] Video title extracted from `message`
- [ ] Video URL extracted from `data.url`
- [ ] Title and URL included in the generated content
- [ ] No fabricated or invalid links