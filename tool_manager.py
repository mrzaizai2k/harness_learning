"""
Tool Manager
Centralized tool definitions for the DeepAgentRunner.
All tools are defined as standalone functions that can be imported and used.
"""

import os
import shutil
from pathlib import Path
from typing import Literal

import requests
from langchain_core.tools import tool
from openai import OpenAI


@tool
def list_files(directory: str = "/") -> str:
    """List files in a directory."""
    # Note: This will be wrapped with crash controller and backend in DeepAgentRunner
    pass


@tool
def read_file(path: str) -> str:
    """Read a file's contents."""
    # Note: This will be wrapped with crash controller and backend in DeepAgentRunner
    pass


@tool
def count_words(text: str) -> int:
    """Count words in a string."""
    # Note: This will be wrapped with crash controller in DeepAgentRunner
    pass


@tool
def download_image(search_result: dict, filename: str = "social_image.png") -> str:
    """
    Download the first image from web search results for social media posts.

    Args:
        search_result: Dictionary containing web search results with 'images' key
        filename: Name for the saved image file (default: 'social_image.png')

    Returns:
        String message indicating success or failure with the saved path
    """
    try:
        OUTPUT_DIR = Path("output")
        OUTPUT_DIR.mkdir(exist_ok=True)

        images = search_result.get("images", [])

        if not images:
            for result in search_result.get("results", []):
                if result.get("images"):
                    images = result["images"]
                    break

        if not images:
            return "Error: No images found in search results"

        first_img_url = images[0]
        save_path = OUTPUT_DIR / filename

        response = requests.get(first_img_url, timeout=30, stream=True)
        response.raise_for_status()

        with open(save_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return f"Social image successfully saved to {save_path.resolve()}"

    except requests.exceptions.RequestException as e:
        return f"Error downloading image: {str(e)}"
    except Exception as e:
        return f"Error saving social image: {str(e)}"


@tool
def move_file(src_path: str, dest_path: str) -> str:
    """
    Move a file from src_path to dest_path, creating any necessary directories.

    Args:
        src_path: The source file path.
        dest_path: The destination file path.

    Returns:
        A success message or an error message if the operation fails.
    """
    try:
        if not os.path.isfile(src_path):
            return f"Error: Source file does not exist: {src_path}"

        dest_dir = os.path.dirname(dest_path)
        os.makedirs(dest_dir, exist_ok=True)

        shutil.move(src_path, dest_path)

        return f"File moved successfully from {src_path} to {dest_path}"
    except Exception as e:
        return f"Error moving file: {e}"


@tool
def web_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news"] = "general",
) -> dict:
    """Search the web for current information.

    Args:
        query: The search query (be specific and detailed)
        max_results: Number of results to return (default: 5)
        topic: "general" for most queries, "news" for current events

    Returns:
        Search results with titles, URLs, and content excerpts.
    """
    try:
        from tavily import TavilyClient

        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            return {"error": "TAVILY_API_KEY not set in environment"}

        client = TavilyClient(api_key=api_key)
        return client.search(
            query,
            max_results=max_results,
            topic=topic,
            include_images=True,
        )
    except Exception as e:
        return {"error": f"Search failed: {str(e)}"}


@tool
def generate_hashtags(text: str, max_tags: int = 10) -> str:
    """
    Generate relevant hashtags for the given text input.

    Args:
        text: Text prompt to generate hashtags for.
        max_tags: Maximum number of hashtags to generate.

    Returns:
        A comma-separated string of hashtags.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "Error: OPENAI_API_KEY not set in environment"

    client = OpenAI(api_key=api_key)

    try:
        system_prompt = "You are a social media expert creating relevant hashtags."
        user_prompt = (
            f"Generate up to {max_tags} relevant hashtags for this text:\n\n"
            f"{text}\n\nHashtags:"
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=60,
            temperature=0.7,
        )

        hashtags = response.choices[0].message.content.strip()

        if not hashtags.startswith("#"):
            tags = [
                h.strip()
                for h in hashtags.replace("\n", ",").split(",")
                if h.strip()
            ]
            tags = [ht if ht.startswith("#") else f"#{ht}" for ht in tags]
            hashtags = ", ".join(tags)

        return hashtags

    except Exception as e:
        return f"Error generating hashtags: {e}"