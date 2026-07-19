"""
docker_sandbox.py
==================
Adapter that lets deepagents use `pydantic_ai_backends.DockerSandbox` as its
sandbox backend, so you get deepagents' agent runtime (tool derivation,
checkpointing, `create_deep_agent`) driving a container that pydantic-ai's
own DockerSandbox manages (runtime presets, named/reusable containers,
volume mounts, idle timeout).

Why an adapter, not "just use one class for both"
--------------------------------------------------
pydantic-ai-backend's `DockerSandbox` and deepagents' `BaseSandbox` solve
overlapping problems but are different protocols:

  * pydantic's `DockerSandbox` extends *its own* `BaseSandbox` and implements
    `read()` / `write()` / `edit()` directly against the container (with
    encoding detection, PDF text extraction, etc.), plus `execute()`.
  * deepagents' `BaseSandbox` is an ABC that *derives* `ls` / `read` / `edit`
    / `grep` / `glob` from just two primitives you provide: `execute()` and
    `upload_files()` (+ `download_files()`).

The good news: the dataclasses line up field-for-field
(`ExecuteResponse(output, exit_code, truncated)`,
`WriteResult(path, error)`, `EditResult(path, occurrences, error)`), so the
bridge is just three methods:

  * `execute()`       -> pure passthrough to `DockerSandbox.execute()`
  * `upload_files()`  -> built on `DockerSandbox.write()`
  * `download_files()`-> built on `DockerSandbox.read_bytes()`, with an
                         existence check via `execute()` first (since
                         `read_bytes()` returns `b""` for both "missing"
                         and "legitimately empty" files -- that ambiguity
                         needs to be resolved before deepagents sees it)

Everything else deepagents' agent calls (`ls`, `read`, `grep`, `glob`, and
even `write`/`edit` when routed through the agent's tools) comes for free
from `BaseSandbox`, built on top of those three methods. Pydantic's own
`read()` / `write()` / `edit()` are only used indirectly, as thin transports
(`write()` for upload, `read_bytes()` for download) -- their fancier
behavior (chardet detection, PDF extraction) isn't exercised here since
deepagents does its own file-type handling in its `read()`.
"""

from __future__ import annotations

import asyncio
import shlex

from pydantic_ai_backends import DockerSandbox, RuntimeConfig

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox


class PydanticDockerSandboxBackend(BaseSandbox):
    """deepagents sandbox backend, backed by a `pydantic_ai_backends.DockerSandbox`."""

    def __init__(self, sandbox: DockerSandbox):
        self._sandbox = sandbox

    @classmethod
    def create(
        cls,
        image: str = "python:3.12-slim",
        *,
        runtime: RuntimeConfig | str | None = None,
        container_name: str | None = None,
        volumes: dict[str, str] | None = None,
        work_dir: str = "/workspace",
        network_mode: str | None = None,
        idle_timeout: int = 3600,
        session_id: str | None = None,
    ) -> "PydanticDockerSandboxBackend":
        """Convenience constructor mirroring `DockerSandbox`'s own kwargs.

        Args mirror `pydantic_ai_backends.DockerSandbox.__init__` directly --
        see that class's docstring for details (runtime presets,
        `container_name` for reusable containers, `volumes` for persistent
        storage, etc.).
        """
        sandbox = DockerSandbox(
            image=image,
            runtime=runtime,
            container_name=container_name,
            volumes=volumes,
            work_dir=work_dir,
            network_mode=network_mode,
            idle_timeout=idle_timeout,
            session_id=session_id,
        )
        return cls(sandbox)

    # ------------------------------------------------------------------ #
    # SandboxBackendProtocol
    # ------------------------------------------------------------------ #
    @property
    def id(self) -> str:
        return self._sandbox.session_id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        # Identical ExecuteResponse shape on both sides -- pure passthrough.
        return self._sandbox.execute(command, timeout=timeout)

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        # DockerSandbox.execute() is sync (docker-py has no async client);
        # offload to a thread so async callers don't block the event loop.
        return await asyncio.to_thread(self.execute, command, timeout=timeout)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            result = self._sandbox.write(path, content)
            if result.error:
                responses.append(FileUploadResponse(path=path, error=result.error))
            else:
                responses.append(FileUploadResponse(path=result.path or path))
        return responses

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return await asyncio.to_thread(self.upload_files, files)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            # read_bytes() returns b"" for both "missing" and "empty" files.
            # Disambiguate with a cheap existence check before trusting an
            # empty result.
            check = self._sandbox.execute(f"test -e {shlex.quote(path)}")
            if check.exit_code != 0:
                responses.append(FileDownloadResponse(path=path, content=None, error="file_not_found"))
                continue
            content = self._sandbox.read_bytes(path)
            responses.append(FileDownloadResponse(path=path, content=content))
        return responses

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return await asyncio.to_thread(self.download_files, paths)

    # ------------------------------------------------------------------ #
    # lifecycle passthroughs
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Pre-warm the container (otherwise it starts lazily on first use)."""
        self._sandbox.start()

    def is_alive(self) -> bool:
        return self._sandbox.is_alive()

    def close(self) -> None:
        """Stop (and, unless a `container_name` was given, remove) the container."""
        self._sandbox.stop()


class PydanticDockerSandboxManager:
    """Multi-user session manager built on `PydanticDockerSandboxBackend`.

    Gives each user_id its own named, reusable container + persistent host
    directory, mirroring pydantic-ai-backend's own `SessionManager` pattern
    but wired up for deepagents.
    """

    def __init__(
        self,
        default_runtime: RuntimeConfig | str | None = "python-minimal",
        workspace_root: str = "/tmp/deepagents-workspaces",  # noqa: S108
    ) -> None:
        self._default_runtime = default_runtime
        self._workspace_root = workspace_root
        self._sandboxes: dict[str, PydanticDockerSandboxBackend] = {}

    def get_or_create(self, user_id: str) -> PydanticDockerSandboxBackend:
        if user_id in self._sandboxes:
            return self._sandboxes[user_id]

        host_dir = f"{self._workspace_root}/{user_id}"
        backend = PydanticDockerSandboxBackend.create(
            runtime=self._default_runtime,
            container_name=f"deepagents-{user_id}",
            volumes={host_dir: "/workspace"},
            work_dir="/workspace",
            session_id=user_id,
        )
        self._sandboxes[user_id] = backend
        return backend

    def close(self, user_id: str) -> None:
        backend = self._sandboxes.pop(user_id, None)
        if backend is not None:
            backend.close()

    def close_all(self) -> None:
        for user_id in list(self._sandboxes):
            self.close(user_id)