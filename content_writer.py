#!/usr/bin/env python3
import warnings
warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")
"""
Content Builder Agent
A content writer agent configured entirely through files on disk:
- AGENTS.md defines brand voice and style guide
- skills/ provides specialized workflows (blog posts, social media)
- skills/*/scripts/ provides tools bundled with each skill
- subagents handle research and other delegated tasks
Usage:
    uv run python content_writer.py "Write a blog post about AI agents"
    uv run python content_writer.py "Create a LinkedIn post about prompt engineering"
"""
import asyncio
import os
import sys
from pathlib import Path
from typing import Literal
import shutil
import yaml
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
import requests
from openai import OpenAI
    
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain.agents.middleware import (
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
    ToolRetryMiddleware,
    
)
from dotenv import load_dotenv
load_dotenv()
 
EXAMPLE_DIR = Path(__file__).parent
print("EXAMPLE_DIR", EXAMPLE_DIR)
console = Console()
 
 
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
        # Ensure output directory exists
        OUTPUT_DIR.mkdir(exist_ok=True)
        
        # Extract image URLs from search result
        images = search_result.get("images", [])
        
        # Fallback: check if images are nested in results
        if not images:
            for result in search_result.get("results", []):
                if result.get("images"):
                    images = result["images"]
                    break
        
        if not images:
            return "Error: No images found in search results"
        
        # Get the first image URL
        first_img_url = images[0]
        
        # Define the save path
        save_path = OUTPUT_DIR / filename
        
        # Download the image
        console.print(f"[dim]Downloading social image from: {first_img_url}[/]")
        response = requests.get(first_img_url, timeout=30, stream=True)
        response.raise_for_status()
        
        # Save the image
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
 
        # Create destination directories if they don't exist
        dest_dir = os.path.dirname(dest_path)
        os.makedirs(dest_dir, exist_ok=True)
 
        # Move the file
        shutil.move(src_path, dest_path)
 
        return f"File moved successfully from {src_path} to {dest_path}"
    except Exception as e:
        return f"Error moving file: {e}"
    
# Web search tool for the researcher subagent
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
        return client.search(query, max_results=max_results, topic=topic, include_images=True)
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
        user_prompt = f"Generate up to {max_tags} relevant hashtags for this text:\n\n{text}\n\nHashtags:"
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=60,
            temperature=0.7,
        )
        hashtags = response.choices[0].message.content.strip()
        # Normalize format
        if not hashtags.startswith("#"):
            tags = [h.strip() for h in hashtags.replace("\n", ",").split(",") if h.strip()]
            tags = [ht if ht.startswith("#") else f"#{ht}" for ht in tags]
            hashtags = ", ".join(tags)
        return hashtags
    except Exception as e:
        return f"Error generating hashtags: {e}"
 
 
def load_subagents(config_path: Path) -> list:
    """Load subagent definitions from YAML and wire up tools.
    
    NOTE: This is a custom utility for this example. Unlike `memory` and `skills`,
    deepagents doesn't natively load subagents from files - they're normally
    defined inline in the create_deep_agent() call. We externalize to YAML here
    to keep configuration separate from code.
    """
    # Map tool names to actual tool objects
    available_tools = {
        "web_search": web_search,
    }
    
    if not config_path.exists():
        console.print(f"[yellow]Warning: Subagents config not found at {config_path}[/]")
        return []
    
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        if not config:
            console.print("[yellow]Warning: Empty subagents configuration[/]")
            return []
        
        subagents = []
        for name, spec in config.items():
            if not isinstance(spec, dict):
                console.print(f"[yellow]Warning: Invalid spec for subagent '{name}', skipping[/]")
                continue
            
            subagent = {
                "name": name,
                "description": spec.get("description", ""),
                "system_prompt": spec.get("system_prompt", ""),
            }
            
            if "model" in spec:
                subagent["model"] = spec["model"]
            
            if "tools" in spec:
                tools = []
                for tool_name in spec["tools"]:
                    if tool_name in available_tools:
                        tools.append(available_tools[tool_name])
                    else:
                        console.print(f"[yellow]Warning: Unknown tool '{tool_name}' for subagent '{name}'[/]")
                subagent["tools"] = tools
            
            subagents.append(subagent)
        
        return subagents
    except Exception as e:
        console.print(f"[red]Error loading subagents: {e}[/]")
        return []
 
def create_content_writer():
    """Create a content writer agent configured by filesystem files."""
    # Validate required API keys
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        console.print("[red]Error: No API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env file[/]")
        sys.exit(1)
        
    from langchain_openai import ChatOpenAI
    qwen_client = ChatOpenAI(
        model="qwen-coder",
        max_tokens=30_000,
        timeout=None,
        max_retries=2,
        base_url="http://161.248.3.16:7979/qwen3_6_35b_a3b/v1",
        api_key="dummy-key",
    )
    
    return create_deep_agent(
        # model="openai:gpt-5.4",
        model=qwen_client,
        memory=["./AGENTS.md"],
        skills=["./skills/"],
        middleware=[
            # Retry model calls on rate limits, timeouts, and 5xx errors
            ModelRetryMiddleware(max_retries=3, backoff_factor=2.0, initial_delay=1.0),
            # If the primary model is fully down, fall back to an alternative
            ModelFallbackMiddleware("gpt-5.5"),
            # Retry specific tools that hit external APIs (not all tools)
            ToolRetryMiddleware(
                max_retries=2,
                tools=["search", "fetch_url"],
                retry_on=(TimeoutError, ConnectionError),
            ),
        ],
        tools=[generate_hashtags, download_image, web_search, move_file],
        subagents=load_subagents(EXAMPLE_DIR / "subagents.yaml"),
        backend=FilesystemBackend(root_dir=EXAMPLE_DIR),
    )
 
class AgentDisplay:
    """Manages the display of agent progress."""
    
    def __init__(self):
        self.printed_count = 0
        self.current_status = ""
        self.spinner = Spinner("dots", text="Thinking...")
    
    def update_status(self, status: str):
        """Update the current status message."""
        self.current_status = status
        self.spinner = Spinner("dots", text=status)
    
    def print_message(self, msg):
        """Print a message with nice formatting."""
        if isinstance(msg, HumanMessage):
            console.print(Panel(str(msg.content), title="You", border_style="blue"))
        
        elif isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, list):
                text_parts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                content = "\n".join(text_parts)
            
            if content and content.strip():
                console.print(Panel(Markdown(content), title="Agent", border_style="green"))
            
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    name = tc.get("name", "unknown")
                    args = tc.get("args", {})
                    
                    if name == "task":
                        desc = args.get("description", "researching...")
                        console.print(f"  [bold magenta]>> Researching:[/] {desc[:60]}...")
                        self.update_status(f"Researching: {desc[:40]}...")
                    
                    elif name in ("download_cover_image", "download_social_image"):
                        console.print(f"  [bold cyan]>> Downloading cover image...[/]")
                        self.update_status("Downloading image...")
                    
                    elif name == "write_file":
                        path = args.get("file_path", "file")
                        console.print(f"  [bold yellow]>> Writing:[/] {path}")
                    
                    elif name == "web_search":
                        query = args.get("query", "")
                        console.print(f"  [bold blue]>> Searching:[/] {query[:50]}...")
                        self.update_status(f"Searching: {query[:30]}...")
        
        elif isinstance(msg, ToolMessage):
            name = getattr(msg, "name", "")
            
            if name in ("download_cover_image", "download_social_image"):
                if "successfully saved" in msg.content.lower():
                    console.print(f"  [green]✓ {msg.content}[/]")
                else:
                    console.print(f"  [red]✗ {msg.content}[/]")
            
            elif name == "write_file":
                console.print(f"  [green]✓ File written[/]")
            
            elif name == "task":
                console.print(f"  [green]✓ Research complete[/]")
            
            elif name == "web_search":
                if "error" not in msg.content.lower():
                    console.print(f"  [green]✓ Found results[/]")
 
async def main():
    """Run the content writer agent with streaming output."""
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
    else:
        task = "Write a blog post about how AI agents are transforming software development"
    
    console.print()
    console.print("[bold blue]Content Builder Agent[/]")
    console.print(f"[dim]Task: {task}[/]")
    console.print()
    
    try:
        agent = create_content_writer()
    except Exception as e:
        console.print(f"[red]Failed to create agent: {e}[/]")
        return
    
    display = AgentDisplay()
    
    console.print() 
    
    # Use Live display for spinner during waiting periods
    with Live(display.spinner, console=console, refresh_per_second=10, transient=True) as live:
        try:
            async for chunk in agent.astream(
                {"messages": [("user", task)]},
                config={"configurable": {"thread_id": "content-writer-demo"}},
                stream_mode="values",
            ):
                if "messages" in chunk:
                    messages = chunk["messages"]
                    if len(messages) > display.printed_count:
                        # Temporarily stop spinner to print
                        live.stop()
                        for msg in messages[display.printed_count:]:
                            display.print_message(msg)
                        display.printed_count = len(messages)
                        # Resume spinner
                        live.start()
                        live.update(display.spinner)
        except Exception as e:
            live.stop()
            console.print(f"\n[red]Error during execution: {e}[/]")
            return
    
    console.print()
    console.print("[bold green]✓ Done![/]")
 
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/]")
    except Exception as e:
        console.print(f"\n[red]Fatal error: {e}[/]")
        sys.exit(1)
 