import shlex

from langchain_core.tools import tool

from docker_sandbox import PydanticDockerSandboxBackend


def make_graphify_tools(backend: PydanticDockerSandboxBackend, query_timeout: int, build_timeout: int) -> list:
    """Build the sandbox-native graphify toolset, bound to `backend`."""

    @tool
    def find_source_root(hint: str = "") -> str:
        """List files/directories in the sandbox workspace to locate the
        source code project (and to check whether graphify-out/ already
        exists). Optionally pass a `hint` substring (e.g. "src",
        "package.json", "graphify-out") to filter results."""
        result = backend.ls("/")
        if result.error:
            return f"Error: {result.error}"
        entries = sorted(entry["path"] for entry in result.entries)
        if hint:
            entries = [e for e in entries if hint.lower() in e.lower()]
        return "\n".join(entries) if entries else "(no matching entries found)"

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

    @tool
    def graphify_query(question: str) -> str:
        """Ask graphify a plain-English question about the codebase's
        structure and relationships, e.g. 'what connects auth to the
        database?'. Returns explicit paths with real file:line citations,
        each relation tagged EXTRACTED, INFERRED, or AMBIGUOUS."""
        result = backend.execute(f"graphify query {shlex.quote(question)}", timeout=query_timeout)
        if result.exit_code != 0:
            return f"graphify query failed: {result.output}"
        return result.output

    @tool
    def graphify_path(source: str, target: str) -> str:
        """Find the shortest path between two named entities in the code
        graph (e.g. two classes or services)."""
        result = backend.execute(
            f"graphify path {shlex.quote(source)} {shlex.quote(target)}", timeout=query_timeout
        )
        if result.exit_code != 0:
            return f"graphify path failed: {result.output}"
        return result.output

    @tool
    def graphify_explain(entity: str) -> str:
        """Explain a single entity (class/function/module/service): what it
        is, where it's defined, what calls it, and what it calls."""
        result = backend.execute(f"graphify explain {shlex.quote(entity)}", timeout=query_timeout)
        if result.exit_code != 0:
            return f"graphify explain failed: {result.output}"
        return result.output

    return [
        find_source_root,
        graphify_ensure_installed,
        graphify_build,
        graphify_query,
        graphify_path,
        graphify_explain,
    ]