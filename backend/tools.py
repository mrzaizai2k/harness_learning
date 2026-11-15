"""
Custom tools for the content agent, on top of deepagents' built-ins
(ls, read_file, write_file, edit_file, glob, grep, execute, task, write_todos).

Tools return an error string instead of raising: LangGraph only turns
argument-validation errors into a message for the model, and any other
exception would end the run.
"""

import shutil
from pathlib import Path
from typing import Literal

import requests
from langchain_core.tools import tool
from openai import OpenAI
from tavily import TavilyClient

from backend import config

_tavily = TavilyClient()  # reads TAVILY_API_KEY from env
_openai = OpenAI()  # reads OPENAI_API_KEY from env


@tool
def web_search(query: str, max_results: int = 5, topic: Literal["general", "news"] = "general") -> dict:
    """Search the web for current information.

    Args:
        query: The search query (be specific and detailed)
        max_results: Number of results to return
        topic: "general" for most queries, "news" for current events

    Returns:
        Search results with titles, URLs, content excerpts and image URLs.
    """
    try:
        return _tavily.search(query, max_results=max_results, topic=topic, include_images=True)
    except Exception as e:
        return {"error": f"Search failed: {e}"}


@tool
def download_image(search_result: dict, filename: str = "social_image.png") -> str:
    """Download the first image from a web_search result into output/.

    Args:
        search_result: The dict returned by web_search (uses its 'images' key)
        filename: Name for the saved image file

    Returns:
        The saved path, or an error message.
    """
    images = search_result.get("images") or [
        img for r in search_result.get("results", []) for img in r.get("images", [])
    ]
    if not images:
        return "Error: No images found in search results"

    save_path = config.OUTPUT_DIR / filename
    try:
        response = requests.get(images[0], timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        return f"Error downloading image: {e}"
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    save_path.write_bytes(response.content)
    return f"Social image successfully saved to {save_path}"


@tool
def generate_hashtags(text: str, max_tags: int = 10) -> str:
    """Generate relevant hashtags for a piece of text.

    Args:
        text: The text to generate hashtags for
        max_tags: Maximum number of hashtags

    Returns:
        A comma-separated string of hashtags.
    """
    try:
        response = _openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a social media expert creating relevant hashtags."},
                {"role": "user", "content": f"Generate up to {max_tags} relevant hashtags for this text:\n\n{text}\n\nHashtags:"},
            ],
            max_tokens=60,
            temperature=0.7,
        )
    except Exception as e:
        return f"Error generating hashtags: {e}"

    raw = (response.choices[0].message.content or "").replace("\n", ",").replace(" ", ",")
    tags = [t.strip() for t in raw.split(",") if t.strip()]
    return ", ".join(t if t.startswith("#") else f"#{t}" for t in tags)


@tool
def move_file(src_path: str, dest_path: str) -> str:
    """Move a file, creating the destination folder if needed.

    Args:
        src_path: The source file path
        dest_path: The destination file path

    Returns:
        A success or error message.
    """
    src, dest = Path(src_path), Path(dest_path)
    if not src.is_file():
        return f"Error: Source file does not exist: {src_path}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(src, dest)
    return f"File moved successfully from {src_path} to {dest_path}"
