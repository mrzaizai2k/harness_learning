import json
import logging
import os

from openai import OpenAI
from typing_extensions import override

from youtube_search import YouTubeSearch

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("infotainment")


def _get_user_text(context: RequestContext) -> str:
    msg = getattr(context, "message", None)
    if not msg:
        request = getattr(context, "request", None)
        if request:
            params = getattr(request, "params", None)
            if params:
                msg = getattr(params, "message", None)

    if not msg:
        return ""

    texts = []

    for part in getattr(msg, "parts", []):
        root = getattr(part, "root", part)
        if getattr(root, "kind", None) == "text":
            texts.append(root.text)

    return " ".join(texts)


def _get_metadata(context: RequestContext) -> dict:
    try:
        req = getattr(context, "_params", None)
        if not req:
            return {}

        message = getattr(req, "message", None)
        if not message:
            return {}

        return getattr(message, "metadata", {}) or {}

    except Exception:
        return {}


class InfotainmentAgentExecutor(AgentExecutor):
    def __init__(self):
        self.youtube = YouTubeSearch()

    def _build_client(self, metadata: dict) -> OpenAI:
        api_key = (
            metadata.get("OPENAI_API_KEY")
            or metadata.get("openai_api_key")
            or os.getenv("OPENAI_API_KEY")
        )

        base_url = (
            metadata.get("OPENAI_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
        )

        kwargs = {"api_key": api_key}

        if base_url:
            kwargs["base_url"] = base_url

        return OpenAI(**kwargs)

    def _generate_search_query(self, client: OpenAI, request: str) -> str:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Convert the user's request into the BEST YouTube search query.\n"
                        "Return ONLY the search query."
                    ),
                },
                {
                    "role": "user",
                    "content": request,
                },
            ],
        )

        return response.choices[0].message.content.strip()

    def _pick_best_video(
        self,
        client: OpenAI,
        request: str,
        videos: list[dict],
    ) -> dict | None:

        prompt = {
            "user_request": request,
            "videos": [
                {
                    "index": i,
                    "title": v.get("title"),
                    "channel": v.get("channel"),
                    "duration": v.get("duration"),
                }
                for i, v in enumerate(videos)
            ],
        }

        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Choose the video that best matches the user's request.\n"
                        "Return JSON:\n"
                        '{"index":0}'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt, ensure_ascii=False),
                },
            ],
        )

        result = json.loads(response.choices[0].message.content)

        index = result["index"]

        if index < 0 or index >= len(videos):
            return None

        return videos[index]

   
    async def run(self, text: str, metadata: dict | None = None) -> dict:
        """Core logic, decoupled from the A2A event-queue protocol.

        Returns a plain dict: {"success": bool, "message": str, "data": {"url": str}}
        Reusable by both the A2A `execute()` entrypoint and any other caller
        (e.g. the Agent Protocol routes).
        """
        text = (text or "").strip()
        metadata = metadata or {}

        if not text:
            return {"success": False, "message": "Empty request.", "data": {"url": ""}}

        client = self._build_client(metadata)

        logger.info("Generating search query...")
        search_query = self._generate_search_query(client, text)
        logger.info("Search query: %s", search_query)

        videos = self.youtube.search(search_query)
        if not videos:
            return {"success": False, "message": "No YouTube videos found.", "data": {"url": ""}}

        best = self._pick_best_video(client, text, videos)
        if not best:
            return {"success": False, "message": "Unable to select a video.", "data": {"url": ""}}

        return {"success": True, "message": best["title"], "data": {"url": best["url"]}}

    @override
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        text = _get_user_text(context)
        logger.info("text: %s", text)
        metadata = _get_metadata(context)
        logger.info("metadata: %s", metadata)

        result = await self.run(text, metadata)
        await event_queue.enqueue_event(new_agent_text_message(json.dumps(result)))

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        raise NotImplementedError()