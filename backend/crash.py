"""
Simulated crashes, for demoing checkpoint + resume.

`arm()` makes the NEXT tool call raise instead of running. The exception
escapes the graph, the stream ends with a `crash` event, and the last
checkpoint is kept, so `/api/resume` picks up from just before that call.
"""

from langchain.agents.middleware import AgentMiddleware


class CrashMiddleware(AgentMiddleware):
    def __init__(self):
        super().__init__()
        self.armed = False

    def arm(self) -> None:
        self.armed = True

    def wrap_tool_call(self, request, handler):
        if self.armed:
            self.armed = False
            raise RuntimeError(f"Simulated crash during: {request.tool_call['name']}")
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        if self.armed:
            self.armed = False
            raise RuntimeError(f"Simulated crash during: {request.tool_call['name']}")
        return await handler(request)
