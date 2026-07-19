---
name: extract-image
description: Extract image from a web search result and saves it as the blog post cover image. Use when you want to leverage web search results to automatically generate post cover images.
---
# Extract Cover Image from Web Search Skill

## Purpose

This skill leverages web search results to automatically download and save cover images for blog posts. It extracts the first available image from search results and saves it to the appropriate blog directory structure.

## When to Use

- **REQUIRED** for all blog posts that need a cover image
- When you want current, relevant imagery from the web
- When you prefer real images over AI-generated ones

## Tools Required

- `web_search` - To find relevant images
- `download_image` - To save the image to the correct location

## Workflow

### Step 1: Search for Relevant Images

First, perform a web search with a descriptive query related to your blog topic:

```python
search_results = web_search(
    query="AI agents futuristic technology illustration",
    max_results=5,
    topic="general"
)
```

**Best Practices for Search Queries:**

- Be specific and descriptive
- Include visual keywords like "illustration", "diagram", "infographic"
- Mention the style you want: "modern", "futuristic", "professional"

**Example queries:**

- "machine learning neural network visualization"
- "software development team collaboration photo"
- "cloud computing infrastructure diagram"

### Step 2: Download the Cover Image

Use the search results to download and save the cover image:

```python
result = download_image(
    search_result=search_results,
    filename="social_image.png",
)
```

The image will be downloaded to `output/social_image.png`.

## Directory Structure

The image will be saved in this structure initially:

```
output/
└── social_image.png
```

You then need to move and rename the image into this folder structure:

```
blogs/
└── your-blog-post-slug/
    └── hero.png          # Cover image saved here
```

example tool to move file

move_file(src_path: str, dest_path: str)

## Complete Example

```python
# 1. Search for an image about AI agents
search_results = web_search(
    query="AI agents automation futuristic illustration",
    max_results=2
)

# 2. Download the first image as the blog cover
message = download_image(
    search_result=search_results,
    filename="social_image.png",
)

# 3. Copy and rename file
move_file(src_path: str, dest_path: str)
```

# Result: Image saved to blogs/ai-agents-transforming-development/hero.png

```

## Error Handling
If an error occurs:
- Try to handle it gracefully.
- Refine the search query or try different queries to find a suitable image.

## Quality Checklist
Before considering this step complete:
- [ ] Web search returned results with images
- [ ] Cover image saved to `blogs/<slug>/hero.png`
- [ ] Directory structure created correctly
- [ ] Image file is accessible and not corrupted
- [ ] Slug matches the blog post slug exactly

## Tips for Best Results
1. **Be specific in searches:** For example, "Python programming code editor" is better than "coding".
2. **Try multiple searches:** If the first search has no good images, refine your query.
3. **Match content tone:** For a professional blog, use professional imagery.
4. **Consider image context:** Ensure the image relates clearly to your blog topic.
```
