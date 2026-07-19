"""
docker_sandbox.py
==================
Adapter that lets deepagents use `pydantic_ai_backends.DockerSandbox` as its
sandbox backend, with automatic path scoping to the working directory.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
import shlex
from pathlib import Path, PurePosixPath

from pydantic_ai_backends import DockerSandbox, RuntimeConfig

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox


class PydanticDockerSandboxBackend(BaseSandbox):
    """deepagents sandbox backend, backed by a `pydantic_ai_backends.DockerSandbox`."""

    def __init__(
        self, 
        sandbox: DockerSandbox, 
        work_dir: str = "/workspace",
        auto_copy_files: bool = False,
        source_dir: str | None = None,
    ):
        self._sandbox = sandbox
        self._work_dir = work_dir.rstrip('/')
        self._auto_copy_files = auto_copy_files
        self._source_dir = source_dir

    def _normalize_path(self, path: str) -> str:
        """
        Normalize a path to be relative to the working directory.
        
        - If path is absolute and starts with work_dir, keep as-is
        - If path is absolute but NOT under work_dir, make it relative to work_dir
        - If path is relative, join with work_dir
        - Special case: "/" becomes work_dir
        """
        path = path.strip()
        
        # Special case: root directory maps to work_dir
        if path == "/" or path == "":
            return self._work_dir
        
        # If it's already absolute and under work_dir, keep it
        if path.startswith(self._work_dir + "/") or path == self._work_dir:
            return path
        
        # If it's absolute but not under work_dir, strip leading / and join
        if path.startswith("/"):
            path = path.lstrip("/")
        
        # Join relative path with work_dir
        normalized = str(PurePosixPath(self._work_dir) / path)
        return normalized

    def _read_dockerignore(self, source_dir: str) -> list[str]:
        """Read .dockerignore patterns."""
        dockerignore_path = os.path.join(source_dir, ".dockerignore")
        if not os.path.exists(dockerignore_path):
            return []
        
        with open(dockerignore_path) as f:
            patterns = [
                line.strip() 
                for line in f 
                if line.strip() and not line.startswith("#")
            ]
        return patterns

    def _should_ignore(self, path: str, ignore_patterns: list[str]) -> bool:
        """Check if path matches any .dockerignore pattern."""
        path = path.lstrip("/")
        
        for pattern in ignore_patterns:
            # Direct match
            if fnmatch.fnmatch(path, pattern):
                return True
            
            # Directory match (pattern ends with /)
            if pattern.endswith("/"):
                if path.startswith(pattern) or fnmatch.fnmatch(path + "/", pattern):
                    return True
            
            # Wildcard directory match
            if "**" in pattern:
                # Convert ** to regex-like matching
                pattern_parts = pattern.split("**")
                if len(pattern_parts) == 2:
                    prefix, suffix = pattern_parts
                    if path.startswith(prefix.rstrip("/")) and path.endswith(suffix.lstrip("/")):
                        return True
            
            # Check if any parent directory matches
            parts = path.split("/")
            for i in range(len(parts)):
                partial = "/".join(parts[:i+1])
                if fnmatch.fnmatch(partial, pattern.rstrip("/")):
                    return True
        
        return False

    def _copy_project_files(self, source_dir: str) -> None:
        """Copy all project files (respecting .dockerignore) into the container."""
        if not os.path.isdir(source_dir):
            raise ValueError(f"Source directory does not exist: {source_dir}")
        
        ignore_patterns = self._read_dockerignore(source_dir)
        
        # Always ignore these
        default_ignores = [
            ".git",
            ".git/**",
            "__pycache__",
            "**/__pycache__",
            "**/*.pyc",
            ".venv",
            ".venv/**",
            "venv",
            "venv/**",
            ".env",
            "*.egg-info",
            "*.egg-info/**",
            ".pytest_cache",
            ".pytest_cache/**",
            "state.json",
            "memory.json",
            ".DS_Store",
        ]
        ignore_patterns.extend(default_ignores)
        
        files_to_upload: list[tuple[str, bytes]] = []
        
        # Walk through the project directory
        for root, dirs, files in os.walk(source_dir):
            # Get relative path from source_dir
            rel_root = os.path.relpath(root, source_dir)
            if rel_root == ".":
                rel_root = ""
            
            # Filter out ignored directories (modify dirs in-place to prevent descent)
            original_dirs = dirs[:]
            dirs[:] = []
            for d in original_dirs:
                rel_dir_path = os.path.join(rel_root, d) if rel_root else d
                if not self._should_ignore(rel_dir_path, ignore_patterns):
                    dirs.append(d)
            
            # Add files that aren't ignored
            for file in files:
                rel_path = os.path.join(rel_root, file) if rel_root else file
                
                if self._should_ignore(rel_path, ignore_patterns):
                    continue
                
                full_path = os.path.join(root, file)
                try:
                    with open(full_path, "rb") as f:
                        content = f.read()
                    files_to_upload.append((rel_path, content))
                except Exception as e:
                    print(f"Warning: Could not read {rel_path}: {e}")
        
        # Upload all files to the container
        if files_to_upload:
            print(f"Uploading {len(files_to_upload)} files to container...")
            results = self.upload_files(files_to_upload)
            
            errors = [r for r in results if r.error]
            if errors:
                print(f"Warning: {len(errors)} files failed to upload")
                for err in errors[:5]:  # Show first 5 errors
                    print(f"  - {err.path}: {err.error}")
            else:
                print(f"✓ Successfully uploaded {len(files_to_upload)} files")

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
        auto_copy_files: bool = False,
        source_dir: str | None = None,
    ) -> "PydanticDockerSandboxBackend":
        """Convenience constructor mirroring `DockerSandbox`'s own kwargs.
        
        Args:
            image: Docker image to use.
            runtime: RuntimeConfig or name of built-in runtime.
            container_name: Stable container name for reuse.
            volumes: Host-to-container volume mappings.
            work_dir: Working directory inside container.
            network_mode: Docker network mode.
            idle_timeout: Timeout in seconds for idle cleanup.
            session_id: Unique identifier for this sandbox session.
            auto_copy_files: If True, automatically copy files from source_dir.
            source_dir: Directory to copy files from (defaults to current directory).
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
        
        backend = cls(
            sandbox, 
            work_dir=work_dir,
            auto_copy_files=auto_copy_files,
            source_dir=source_dir,
        )
        
        # Auto-copy files if enabled
        if auto_copy_files:
            if source_dir is None:
                source_dir = os.getcwd()
            
            # Start container first
            backend.start()
            
            # Then copy files
            backend._copy_project_files(source_dir)
        
        return backend

    # ------------------------------------------------------------------ #
    # SandboxBackendProtocol - with path normalization
    # ------------------------------------------------------------------ #
    @property
    def id(self) -> str:
        return self._sandbox.session_id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        # Execute commands with work_dir as the working directory
        wrapped_command = f"cd {shlex.quote(self._work_dir)} && {command}"
        return self._sandbox.execute(wrapped_command, timeout=timeout)

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return await asyncio.to_thread(self.execute, command, timeout=timeout)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            normalized_path = self._normalize_path(path)
            result = self._sandbox.write(normalized_path, content)
            if result.error:
                responses.append(FileUploadResponse(path=normalized_path, error=result.error))
            else:
                responses.append(FileUploadResponse(path=result.path or normalized_path))
        return responses

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return await asyncio.to_thread(self.upload_files, files)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            normalized_path = self._normalize_path(path)
            check = self._sandbox.execute(f"test -e {shlex.quote(normalized_path)}")
            if check.exit_code != 0:
                responses.append(FileDownloadResponse(path=normalized_path, content=None, error="file_not_found"))
                continue
            content = self._sandbox.read_bytes(normalized_path)
            responses.append(FileDownloadResponse(path=normalized_path, content=content))
        return responses

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return await asyncio.to_thread(self.download_files, paths)

    # ------------------------------------------------------------------ #
    # Override BaseSandbox high-level methods to inject path normalization
    def ls(self, path: str = "/"):
        """Override ls to normalize the path before delegating to parent."""
        normalized_path = self._normalize_path(path)
        return super().ls(normalized_path)

    async def als(self, path: str = "/"):
        """Async version of ls with path normalization."""
        return await asyncio.to_thread(self.ls, path)

    def read(self, path: str):
        """Override read to normalize the path before delegating to parent."""
        normalized_path = self._normalize_path(path)
        return super().read(normalized_path)

    async def aread(self, path: str):
        """Async version of read with path normalization."""
        return await asyncio.to_thread(self.read, path)

    def write(self, path: str, content: str):
        """Override write to normalize the path before delegating to parent."""
        normalized_path = self._normalize_path(path)
        return super().write(normalized_path, content)

    async def awrite(self, path: str, content: str):
        """Async version of write with path normalization."""
        return await asyncio.to_thread(self.write, path, content)

    def edit(self, path: str, old_str: str, new_str: str, *, occurrences: int | None = None):
        """Override edit to normalize the path before delegating to parent."""
        normalized_path = self._normalize_path(path)
        return super().edit(normalized_path, old_str, new_str, occurrences=occurrences)

    async def aedit(self, path: str, old_str: str, new_str: str, *, occurrences: int | None = None):
        """Async version of edit with path normalization."""
        return await asyncio.to_thread(self.edit, path, old_str, new_str, occurrences=occurrences)

    def grep(self, pattern: str, path: str = "/", *, case_sensitive: bool = True):
        """Override grep to normalize the path before delegating to parent."""
        normalized_path = self._normalize_path(path)
        return super().grep(pattern, normalized_path, case_sensitive=case_sensitive)

    async def agrep(self, pattern: str, path: str = "/", *, case_sensitive: bool = True):
        """Async version of grep with path normalization."""
        return await asyncio.to_thread(self.grep, pattern, path, case_sensitive=case_sensitive)

    def glob(self, pattern: str, path: str = "/"):
        """Override glob to normalize the path before delegating to parent."""
        normalized_path = self._normalize_path(path)
        return super().glob(pattern, normalized_path)

    async def aglob(self, pattern: str, path: str = "/"):
        """Async version of glob with path normalization."""
        return await asyncio.to_thread(self.glob, pattern, path)

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
    """Multi-user session manager built on `PydanticDockerSandboxBackend`."""

    def __init__(
        self,
        default_runtime: RuntimeConfig | str | None = "python-minimal",
        workspace_root: str = "/tmp/deepagents-workspaces",  # noqa: S108
        auto_copy_files: bool = False,
        source_dir: str | None = None,
    ) -> None:
        self._default_runtime = default_runtime
        self._workspace_root = workspace_root
        self._auto_copy_files = auto_copy_files
        self._source_dir = source_dir or os.getcwd()
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
            auto_copy_files=self._auto_copy_files,
            source_dir=self._source_dir,
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