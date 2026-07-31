import shlex

from langchain_core.tools import tool
from rapidfuzz import process, fuzz

from docker_sandbox import PydanticDockerSandboxBackend


def make_graphify_tools(backend: PydanticDockerSandboxBackend, query_timeout: int, build_timeout: int) -> list:
    """Build the sandbox-native graphify toolset, bound to `backend`."""

    @tool
    def graphify_ensure_installed() -> str:
        """Check whether the `graphify` CLI is available in the sandbox;
        install it (via pip) if it is missing. Call this once before the
        first build/query/path/explain call."""
        check = backend.execute("graphify --version")
        if check.exit_code == 0:
            return f"graphify already installed: {(check.output or '').strip()}"
        install = backend.execute("pip install --quiet graphifyy", timeout=180)
        if install.exit_code != 0:
            return f"Failed to install graphify: {install.output}"
        verify = backend.execute("graphify --version")
        if verify.exit_code == 0:
            return f"Installed graphify: {(verify.output or '').strip()}"
        return f"Install ran but `graphify` is still not on PATH: {verify.output}"

    @tool
    def graphify_build(path: str = ".", update: bool = False, mode: str | None = None, code_only: bool = False) -> str:
        """Build (or update) the Graphify knowledge graph for the codebase
        at `path` inside the sandbox. Produces graphify-out/graph.html,
        GRAPH_REPORT.md, and graph.json under `path`. Set `update=True` to
        re-scan only what changed instead of rebuilding from scratch. Set
        `mode="deep"` for a deeper multi-pass analysis. Set `code_only=True`
        to index only code via local AST parsing and skip docs/papers/images
        that require an LLM API key for semantic extraction — use this if
        the build fails with a "no LLM API key found" error, or if you only
        care about code structure and not doc/paper content."""
        cmd = f"graphify {shlex.quote(path)}"
        if update:
            cmd += " --update"
        if mode:
            cmd += f" --mode {shlex.quote(mode)}"
        if code_only:
            cmd += " --code-only"
        result = backend.execute(cmd, timeout=build_timeout)
        if result.exit_code != 0:
            return f"graphify build failed: {result.output}"
        return result.output or "graphify build completed."

    def _graph_json_exists(code_path: str) -> bool:
        check = backend.execute(
            f"test -f {shlex.quote(code_path.rstrip('/') + '/graphify-out/graph.json')}"
        )
        return check.exit_code == 0

    def _missing_graph_msg(cmd_name: str, code_path: str) -> str:
        return (
            f"graphify {cmd_name} failed: no graph.json found under "
            f"{code_path.rstrip('/')}/graphify-out/. Run graphify_build with "
            f"path={code_path!r} first, or pass the correct code_path."
        )

    @tool
    def graphify_query(question: str, code_path: str = ".") -> str:
        """Ask graphify a plain-English question about the codebase's
        structure and relationships, e.g. 'what connects auth to the
        database?'. Returns explicit paths with real file:line citations,
        each relation tagged EXTRACTED, INFERRED, or AMBIGUOUS.

        `code_path` MUST be the same path that was passed to
        `graphify_build` (e.g. "/workspace/code_base_c_test"), since that is
        where graphify-out/graph.json was written. Do not omit it — graphify
        reads graphify-out/graph.json relative to the current directory, so
        this tool `cd`s into code_path before running the command."""
        if not _graph_json_exists(code_path):
            return _missing_graph_msg("query", code_path)
        cmd = f"cd {shlex.quote(code_path)} && graphify query {shlex.quote(question)}"
        result = backend.execute(cmd, timeout=query_timeout)
        if result.exit_code != 0:
            return f"graphify query failed: {result.output}"
        return result.output

    @tool
    def graphify_path(source: str, target: str, code_path: str = ".") -> str:
        """Find the shortest path between two named entities in the code
        graph (e.g. two classes or services).

        `code_path` MUST match the path passed to `graphify_build` (e.g.
        "/workspace/code_base_c_test"), since that is where the graph was
        written. This tool `cd`s into code_path before running the command."""
        if not _graph_json_exists(code_path):
            return _missing_graph_msg("path", code_path)
        cmd = f"cd {shlex.quote(code_path)} && graphify path {shlex.quote(source)} {shlex.quote(target)}"
        result = backend.execute(cmd, timeout=query_timeout)
        if result.exit_code != 0:
            return f"graphify path failed: {result.output}"
        return result.output

    @tool
    def graphify_explain(entity: str, code_path: str = ".") -> str:
        """Explain a single entity (class/function/module/service): what it
        is, where it's defined, what calls it, and what it calls.

        `code_path` MUST match the path passed to `graphify_build` (e.g.
        "/workspace/code_base_c_test"), since that is where the graph was
        written. This tool `cd`s into code_path before running the command."""
        if not _graph_json_exists(code_path):
            return _missing_graph_msg("explain", code_path)
        cmd = f"cd {shlex.quote(code_path)} && graphify explain {shlex.quote(entity)}"
        result = backend.execute(cmd, timeout=query_timeout)
        if result.exit_code != 0:
            return f"graphify explain failed: {result.output}"
        return result.output

    return [
        graphify_ensure_installed,
        graphify_build,
        graphify_query,
        graphify_path,
        graphify_explain,
    ]