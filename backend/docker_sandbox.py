"""
docker_sandbox.py
==================
Adapter that lets deepagents use `pydantic_ai_backends.DockerSandbox` as its
sandbox backend, with automatic path scoping to the working directory.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
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

logger = logging.getLogger(__name__)


class PydanticDockerSandboxBackend(BaseSandbox):
    """deepagents sandbox backend, backed by a `pydantic_ai_backends.DockerSandbox`."""

    def __init__(
        self,
        sandbox: DockerSandbox,
        work_dir: str = "/workspace",
        auto_copy_files: bool = False,
        source_dir: str | None = None,
    ):
        logger.debug(
            "Initializing PydanticDockerSandboxBackend work_dir=%s auto_copy_files=%s source_dir=%s",
            work_dir, auto_copy_files, source_dir,
        )
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
        logger.debug("Normalizing path: %r", path)
        path = path.strip()

        # Special case: root directory maps to work_dir
        if path == "/" or path == "":
            logger.debug("Path is root, mapping to work_dir: %s", self._work_dir)
            return self._work_dir

        # If it's already absolute and under work_dir, keep it
        if path.startswith(self._work_dir + "/") or path == self._work_dir:
            logger.debug("Path already under work_dir, keeping as-is: %s", path)
            return path

        # If it's absolute but not under work_dir, strip leading / and join
        if path.startswith("/"):
            path = path.lstrip("/")

        # Join relative path with work_dir
        normalized = str(PurePosixPath(self._work_dir) / path)
        logger.debug("Normalized path result: %s", normalized)
        return normalized

    def _read_dockerignore(self, source_dir: str) -> list[str]:
        """Read .dockerignore patterns."""
        dockerignore_path = os.path.join(source_dir, ".dockerignore")
        logger.debug("Reading .dockerignore at: %s", dockerignore_path)
        if not os.path.exists(dockerignore_path):
            logger.debug(".dockerignore not found at %s", dockerignore_path)
            return []

        with open(dockerignore_path) as f:
            patterns = [
                line.strip()
                for line in f
                if line.strip() and not line.startswith("#")
            ]
        logger.debug("Loaded %d ignore patterns from .dockerignore", len(patterns))
        return patterns

    def _should_ignore(self, path: str, ignore_patterns: list[str]) -> bool:
        """Check if path matches any .dockerignore pattern."""
        path = path.lstrip("/")

        for pattern in ignore_patterns:
            # Direct match
            if fnmatch.fnmatch(path, pattern):
                logger.debug("Path %s matched ignore pattern %s (direct match)", path, pattern)
                return True

            # Directory match (pattern ends with /)
            if pattern.endswith("/"):
                if path.startswith(pattern) or fnmatch.fnmatch(path + "/", pattern):
                    logger.debug("Path %s matched ignore pattern %s (directory match)", path, pattern)
                    return True

            # Wildcard directory match
            if "**" in pattern:
                # Convert ** to regex-like matching
                pattern_parts = pattern.split("**")
                if len(pattern_parts) == 2:
                    prefix, suffix = pattern_parts
                    if path.startswith(prefix.rstrip("/")) and path.endswith(suffix.lstrip("/")):
                        logger.debug("Path %s matched ignore pattern %s (wildcard match)", path, pattern)
                        return True

            # Check if any parent directory matches
            parts = path.split("/")
            for i in range(len(parts)):
                partial = "/".join(parts[:i+1])
                if fnmatch.fnmatch(partial, pattern.rstrip("/")):
                    logger.debug("Path %s matched ignore pattern %s (parent dir match: %s)", path, pattern, partial)
                    return True

        return False

    def _copy_project_files(self, source_dir: str) -> None:
        """Copy all project files (respecting .dockerignore) into the container."""
        logger.info("Copying project files from source_dir=%s", source_dir)
        if not os.path.isdir(source_dir):
            logger.debug("Source directory does not exist: %s", source_dir)
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
            # ".env",
            "*.egg-info",
            "*.egg-info/**",
            ".pytest_cache",
            ".pytest_cache/**",
            "state.json",
            "memory.json",
            ".DS_Store",
        ]
        ignore_patterns.extend(default_ignores)
        logger.debug("Total ignore patterns in effect: %d", len(ignore_patterns))

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
                else:
                    logger.debug("Skipping ignored directory: %s", rel_dir_path)

            # Add files that aren't ignored
            for file in files:
                rel_path = os.path.join(rel_root, file) if rel_root else file

                if self._should_ignore(rel_path, ignore_patterns):
                    logger.debug("Skipping ignored file: %s", rel_path)
                    continue

                full_path = os.path.join(root, file)
                try:
                    with open(full_path, "rb") as f:
                        content = f.read()
                    files_to_upload.append((rel_path, content))
                    logger.debug("Queued file for upload: %s (%d bytes)", rel_path, len(content))
                except Exception as e:
                    logger.debug("Could not read %s: %s", rel_path, e)
                    print(f"Warning: Could not read {rel_path}: {e}")

        # Upload all files to the container
        if files_to_upload:
            logger.info("Uploading %d files to container...", len(files_to_upload))
            print(f"Uploading {len(files_to_upload)} files to container...")
            results = self.upload_files(files_to_upload)

            errors = [r for r in results if r.error]
            if errors:
                logger.info("%d files failed to upload", len(errors))
                print(f"Warning: {len(errors)} files failed to upload")
                for err in errors[:5]:  # Show first 5 errors
                    logger.debug("Upload error for %s: %s", err.path, err.error)
                    print(f"  - {err.path}: {err.error}")
            else:
                logger.info("Successfully uploaded %d files", len(files_to_upload))
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
        logger.info(
            "Creating PydanticDockerSandboxBackend image=%s container_name=%s work_dir=%s session_id=%s auto_copy_files=%s",
            image, container_name, work_dir, session_id, auto_copy_files,
        )
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
                logger.debug("source_dir not provided, defaulting to cwd: %s", source_dir)

            # Start container first
            logger.debug("Starting container before auto-copying files")
            backend.start()

            # Then copy files
            backend._copy_project_files(source_dir)

        logger.debug("PydanticDockerSandboxBackend created with id=%s", backend.id)
        return backend

    # ------------------------------------------------------------------ #
    # SandboxBackendProtocol - with path normalization
    # ------------------------------------------------------------------ #
    @property
    def id(self) -> str:
        return self._sandbox.session_id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        # Execute commands with work_dir as the working directory
        logger.info("Executing command in sandbox id=%s: %s", self.id, command)
        return self._sandbox.execute(command, timeout=timeout)

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        logger.debug("aexecute called for command: %s", command)
        return await asyncio.to_thread(self.execute, command, timeout=timeout)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        logger.info("Uploading %d files", len(files))
        responses: list[FileUploadResponse] = []
        for path, content in files:
            normalized_path = self._normalize_path(path)
            logger.debug("Writing file to sandbox: %s (%d bytes)", normalized_path, len(content))
            result = self._sandbox.write(normalized_path, content)
            if result.error:
                logger.debug("Error uploading file %s: %s", normalized_path, result.error)
                responses.append(FileUploadResponse(path=normalized_path, error=result.error))
            else:
                responses.append(FileUploadResponse(path=result.path or normalized_path))
        return responses

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        logger.debug("aupload_files called with %d files", len(files))
        return await asyncio.to_thread(self.upload_files, files)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        logger.info("Downloading %d files", len(paths))
        responses: list[FileDownloadResponse] = []
        for path in paths:
            normalized_path = self._normalize_path(path)
            logger.debug("Checking existence of file: %s", normalized_path)
            check = self._sandbox.execute(f"test -e {shlex.quote(normalized_path)}")
            if check.exit_code != 0:
                logger.debug("File not found: %s", normalized_path)
                responses.append(FileDownloadResponse(path=normalized_path, content=None, error="file_not_found"))
                continue
            content = self._sandbox.read_bytes(normalized_path)
            logger.debug("Read %s bytes from %s", len(content) if content is not None else "unknown", normalized_path)
            responses.append(FileDownloadResponse(path=normalized_path, content=content))
        return responses

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        logger.debug("adownload_files called with %d paths", len(paths))
        return await asyncio.to_thread(self.download_files, paths)

    # ------------------------------------------------------------------ #
    # Override BaseSandbox high-level methods to inject path normalization
    # ------------------------------------------------------------------ #
    def _entry_path(self, entry) -> str | None:
        """Best-effort extraction of a path string from an ls() entry.

        Entries returned by the underlying sandbox's ls() may be plain
        strings, dicts, or objects exposing a `.path` / `.name` attribute
        depending on the backend implementation — handle all of them.
        """
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            return entry.get("path") or entry.get("name")
        for attr in ("path", "name"):
            value = getattr(entry, attr, None)
            if value:
                return value
        return None

    def _is_within_workdir(self, entry_path: str) -> bool:
        """Return True if `entry_path` resolves to somewhere under work_dir."""
        if entry_path.startswith("/"):
            candidate = entry_path
        else:
            # Relative entries are resolved the same way _normalize_path does
            candidate = str(PurePosixPath(self._work_dir) / entry_path)

        return candidate == self._work_dir or candidate.startswith(self._work_dir + "/")

    def _filter_entry_list(self, entry_list: list) -> list:
        """Filter a plain list of ls() entries down to those under work_dir."""
        filtered = []
        dropped = 0
        for entry in entry_list:
            entry_path = self._entry_path(entry)
            if entry_path is None:
                # Can't determine a path for this entry — keep it rather
                # than silently discard data we can't classify.
                filtered.append(entry)
                continue
            if self._is_within_workdir(entry_path):
                filtered.append(entry)
            else:
                dropped += 1
                logger.debug("Filtering out ls() entry outside work_dir: %s", entry_path)

        if dropped:
            logger.debug("Filtered %d entries outside work_dir=%s", dropped, self._work_dir)

        return filtered

    # Common attribute names used by ls()-result wrapper objects (e.g.
    # `LsResult`) across different sandbox backend implementations.
    _LS_RESULT_ENTRY_ATTRS = ("entries", "files", "items", "paths", "results")

    def _filter_entries_to_workdir(self, entries):
        """Drop any ls() entries that fall outside work_dir.

        Handles two shapes:
        1. A plain list/tuple of entries (strings, dicts, or objects).
        2. A wrapper/result object (e.g. `LsResult`) that holds the actual
           entries under an attribute like `.entries` or `.files`. In that
           case we filter the inner list and rebuild the same wrapper type
           rather than returning a bare list, so callers relying on the
           wrapper's shape don't break.
        """
        if entries is None:
            return entries

        # Case 1: already a plain iterable of entries
        if isinstance(entries, (list, tuple)):
            return self._filter_entry_list(list(entries))

        # Case 2: wrapper object — find the attribute holding the entries
        for attr in self._LS_RESULT_ENTRY_ATTRS:
            if not hasattr(entries, attr):
                continue
            raw = getattr(entries, attr)
            if raw is None:
                continue
            try:
                raw_list = list(raw)
            except TypeError:
                continue

            filtered = self._filter_entry_list(raw_list)

            # Try in-place mutation first (works for most mutable objects,
            # including non-frozen dataclasses and mutable pydantic models).
            try:
                setattr(entries, attr, filtered)
                return entries
            except Exception:
                pass

            # Fall back to reconstructing an immutable/frozen object.
            try:
                import dataclasses
                if dataclasses.is_dataclass(entries):
                    return dataclasses.replace(entries, **{attr: filtered})
            except Exception:
                pass

            try:
                # pydantic v1/v2 style copy-with-update
                if hasattr(entries, "model_copy"):
                    return entries.model_copy(update={attr: filtered})
                if hasattr(entries, "copy"):
                    return entries.copy(update={attr: filtered})
            except Exception:
                pass

            logger.debug(
                "Could not filter attribute %s on %s; returning result unfiltered",
                attr, type(entries),
            )
            return entries

        # Unrecognized shape — don't guess, just pass it through.
        logger.debug(
            "ls() returned an unrecognized result type %s with no known entry "
            "attribute; returning unfiltered", type(entries),
        )
        return entries

    def ls(self, path: str = "/", **kwargs):
        """List directory contents, scoped strictly to work_dir.

        The requested path is first normalized into work_dir (as before),
        and any entries the underlying sandbox returns that fall outside
        work_dir are filtered out before returning to the caller.
        """
        logger.debug("ls called with path=%s kwargs=%s", path, kwargs)
        normalized_path = self._normalize_path(path)
        # BaseSandbox.ls() doesn't accept any kwargs, so we ignore them
        entries = super().ls(normalized_path)
        return self._filter_entries_to_workdir(entries)

    async def als(self, path: str = "/", **kwargs):
        """Async version of ls, scoped strictly to work_dir."""
        logger.debug("als called with path=%s kwargs=%s", path, kwargs)
        return await asyncio.to_thread(self.ls, path, **kwargs)

    def read(self, path: str, *args, **kwargs):
        """Override read to normalize the path before delegating to parent."""
        logger.debug("read called with path=%s", path)
        normalized_path = self._normalize_path(path)
        return super().read(normalized_path, *args, **kwargs)

    async def aread(self, path: str, *args, **kwargs):
        """Async version of read with path normalization."""
        logger.debug("aread called with path=%s", path)
        return await asyncio.to_thread(self.read, path, *args, **kwargs)

    def write(self, path: str, content: str, *args, **kwargs):
        """Override write to normalize the path before delegating to parent."""
        logger.debug("write called with path=%s (%d chars)", path, len(content))
        normalized_path = self._normalize_path(path)
        return super().write(normalized_path, content, *args, **kwargs)

    async def awrite(self, path: str, content: str, *args, **kwargs):
        """Async version of write with path normalization."""
        logger.debug("awrite called with path=%s", path)
        return await asyncio.to_thread(self.write, path, content, *args, **kwargs)

    def edit(self, path: str, *args, **kwargs):
        normalized_path = self._normalize_path(path)
        return super().edit(normalized_path, *args, **kwargs)

    async def aedit(self, path: str, *args, **kwargs):
        return await asyncio.to_thread(self.edit, path, *args, **kwargs)

    def grep(self, pattern: str, path: str = "/", *args, **kwargs):
        normalized_path = self._normalize_path(path)
        return super().grep(pattern, normalized_path, *args, **kwargs)

    async def agrep(self, pattern: str, path: str = "/", *args, **kwargs):
        return await asyncio.to_thread(self.grep, pattern, path, *args, **kwargs)

    def glob(self, pattern: str, path: str = "/"):
        """Override glob to normalize the path before delegating to parent."""
        logger.debug("glob called with pattern=%s path=%s", pattern, path)
        normalized_path = self._normalize_path(path)
        return super().glob(pattern, normalized_path)

    async def aglob(self, pattern: str, path: str = "/"):
        """Async version of glob with path normalization."""
        logger.debug("aglob called with pattern=%s path=%s", pattern, path)
        return await asyncio.to_thread(self.glob, pattern, path)

    # ------------------------------------------------------------------ #
    # lifecycle passthroughs
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Pre-warm the container (otherwise it starts lazily on first use)."""
        logger.info("Starting sandbox container id=%s", self.id)
        self._sandbox.start()

    def is_alive(self) -> bool:
        alive = self._sandbox.is_alive()
        logger.debug("is_alive check for id=%s: %s", self.id, alive)
        return alive

    def close(self) -> None:
        """Stop (and, unless a `container_name` was given, remove) the container."""
        logger.info("Closing sandbox container id=%s", self.id)
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
        logger.debug(
            "Initializing PydanticDockerSandboxManager workspace_root=%s auto_copy_files=%s source_dir=%s",
            workspace_root, auto_copy_files, source_dir,
        )
        self._default_runtime = default_runtime
        self._workspace_root = workspace_root
        self._auto_copy_files = auto_copy_files
        self._source_dir = source_dir or os.getcwd()
        self._sandboxes: dict[str, PydanticDockerSandboxBackend] = {}

    def get_or_create(self, user_id: str) -> PydanticDockerSandboxBackend:
        logger.info("get_or_create called for user_id=%s", user_id)
        if user_id in self._sandboxes:
            logger.debug("Returning existing sandbox for user_id=%s", user_id)
            return self._sandboxes[user_id]

        host_dir = f"{self._workspace_root}/{user_id}"
        logger.debug("Creating new sandbox for user_id=%s with host_dir=%s", user_id, host_dir)
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
        logger.info("Sandbox created and registered for user_id=%s", user_id)
        return backend

    def close(self, user_id: str) -> None:
        logger.info("close called for user_id=%s", user_id)
        backend = self._sandboxes.pop(user_id, None)
        if backend is not None:
            backend.close()
        else:
            logger.debug("No sandbox found for user_id=%s, nothing to close", user_id)

    def close_all(self) -> None:
        logger.info("close_all called, closing %d sandboxes", len(self._sandboxes))
        for user_id in list(self._sandboxes):
            self.close(user_id)