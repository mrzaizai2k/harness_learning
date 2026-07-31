"""Async adapter around the Graphify CLI."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}


class GraphifyError(RuntimeError):
    """Raised when Graphify cannot build or query the code graph."""


class GraphifyService:
    """Build a local AST graph and execute bounded natural-language queries."""

    def __init__(
        self,
        source_dir: str | Path,
        output_root: str | Path,
        query_budget: int = 3000,
    ) -> None:
        self.source_dir = Path(source_dir).resolve()
        self.output_root = Path(output_root).resolve()
        self.graph_path = self.output_root / "graphify-out" / "graph.json"
        self.manifest_path = self.output_root / "graphify-out" / "manifest.json"
        self.query_budget = query_budget
        self._build_lock = asyncio.Lock()

    async def query(self, question: str) -> dict[str, Any]:
        await self.ensure_graph()
        stdout = await self._run(
            "query",
            question,
            "--graph",
            str(self.graph_path),
            "--budget",
            str(self.query_budget),
        )
        graph = self._load_graph()
        return {
            "query": question,
            "result": stdout.strip(),
            "graph_path": str(self.graph_path),
            "node_count": len(graph.get("nodes", [])),
            "edge_count": len(graph.get("edges", [])),
        }

    async def ensure_graph(self) -> None:
        if not self.source_dir.is_dir():
            raise GraphifyError(f"Source directory not found: {self.source_dir}")
        if not self._source_files():
            raise GraphifyError(
                f"No C/C++ source files found in: {self.source_dir}"
            )
        if not self._is_stale():
            return

        async with self._build_lock:
            if not self._is_stale():
                return
            await self._run(
                "extract",
                str(self.source_dir),
                "--code-only",
                "--no-cluster",
                "--out",
                str(self.output_root),
            )
            if not self.graph_path.is_file():
                raise GraphifyError(f"Graphify did not create {self.graph_path}")

    def _is_stale(self) -> bool:
        if not self.graph_path.is_file():
            return True
        source_files = self._source_files()
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True
        if not isinstance(manifest, dict):
            return True
        relative_sources = {
            path.relative_to(self.source_dir).as_posix() for path in source_files
        }
        if set(manifest) != relative_sources:
            return True
        graph_mtime = self.graph_path.stat().st_mtime
        return any(
            path.stat().st_mtime > graph_mtime
            for path in source_files
        )

    def _source_files(self) -> list[Path]:
        return [
            path
            for path in self.source_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES
        ]

    def _load_graph(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.graph_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GraphifyError(f"Cannot read Graphify graph: {exc}") from exc
        if not isinstance(payload, dict):
            raise GraphifyError("Graphify graph must be a JSON object")
        return payload

    async def _run(self, *arguments: str) -> str:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "graphify",
            *arguments,
            cwd=str(self.output_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
        stdout, stderr = await process.communicate()
        output = stdout.decode("utf-8", errors="replace")
        error = stderr.decode("utf-8", errors="replace")
        if process.returncode:
            detail = error.strip() or output.strip() or "unknown error"
            raise GraphifyError(f"Graphify failed ({process.returncode}): {detail}")
        return output
