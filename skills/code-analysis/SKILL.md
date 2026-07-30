---
name: code-analysis
description: >-
  Analyze and understand a source code repository using CodeGraph. Before any
  analysis, locate the project's root directory, ensure it has been indexed,
  and then perform semantic code exploration, symbol search, dependency
  analysis, call graph inspection, impact analysis, and repository exploration.
  Use this skill whenever the user asks questions about a codebase, source
  files, architecture, functions, classes, APIs, dependencies, or execution
  flow.
---

# Code Analysis

Use this skill whenever the user wants to understand or analyze a codebase.

Examples:

- Analyze this repository.
- Explain how authentication works.
- Where is `UserService` used?
- What calls `process_payment`?
- Show the architecture of this project.
- Find all implementations of an interface.
- What code is affected if I change this function?
- Which tests should I run after modifying these files?

## Workflow

### Step 1. Locate the source code

If the user did not specify the project directory, first locate the repository.

Look for common project indicators such as:

- `.git`
- `pyproject.toml`
- `package.json`
- `Cargo.toml`
- `pom.xml`
- `go.mod`
- `.codegraph`

Determine the repository root before executing any CodeGraph commands.

---

### Step 2. Check whether CodeGraph has been initialized

Inside the repository root, check whether the project already contains a
`.codegraph` directory.

If `.codegraph` **does not exist**, initialize the project.

```bash
cd <project_root>
codegraph init
```

This scans and indexes the entire codebase.

If `.codegraph` **already exists**, do **not** run `codegraph init`.

---

### Step 3. Always execute CodeGraph inside the repository

Before running **any** CodeGraph command, change into the repository root.

Example:

```bash
cd <project_root>
codegraph explore "authentication flow"
```

Never execute CodeGraph commands from outside the project directory.

---

### Step 4. Choose the appropriate command

#### Explore a feature or concept (preferred)

Use this first for high-level understanding.

```bash
cd <project_root>
codegraph explore "<query>"
```

Examples:

```bash
cd <project_root>
codegraph explore "authentication flow"

codegraph explore "payment processing"

codegraph explore "RAG pipeline"

codegraph explore "how request reaches database"
```

---

#### Search for symbols

```bash
cd <project_root>
codegraph query "<search>"
```

Examples:

```bash
cd <project_root>
codegraph query "UserService"

codegraph query "authenticate"

codegraph query "ChatAgent"
```

---

#### Inspect a symbol or file

```bash
cd <project_root>
codegraph node "<symbol>"
```

or

```bash
cd <project_root>
codegraph node "<file>"
```

Examples:

```bash
cd <project_root>
codegraph node UserService.login

cd <project_root>
codegraph node src/api/router.py
```

---

#### Find callers

```bash
cd <project_root>
codegraph callers "<symbol>"
```

---

#### Find callees

```bash
cd <project_root>
codegraph callees "<symbol>"
```

---

#### Impact analysis

```bash
cd <project_root>
codegraph impact "<symbol>"
```

---

#### Find affected tests

```bash
cd <project_root>
codegraph affected <files...>
```

---

#### Repository structure

```bash
cd <project_root>
codegraph files
```

Useful options:

```bash
cd <project_root>
codegraph files --format tree

cd <project_root>
codegraph files --max-depth 3

cd <project_root>
codegraph files --filter src
```

---

### Step 5. Re-index when necessary

If the repository has changed significantly or CodeGraph reports the index is
out of date:

```bash
cd <project_root>
codegraph sync
```

If a complete rebuild is required:

```bash
cd <project_root>
codegraph index --force
```

If indexing is blocked by a stale lock:

```bash
cd <project_root>
codegraph unlock
```

---

### Step 6. Summarize findings

Summarize:

- Relevant files
- Important symbols
- Execution flow
- Call relationships
- Dependencies
- Potential side effects
- Suggested next investigation steps

Focus on answering the user's question rather than dumping raw source code.

## Rules

- **Always locate the repository before using CodeGraph.**
- **Always `cd` into the repository root before every CodeGraph command.**
- **If `.codegraph` is missing, run `codegraph init` exactly once before analysis.**
- Prefer `explore` for understanding features or architecture.
- Prefer `query` when searching for symbols.
- Use `node` for implementation details.
- Use `callers` and `callees` to understand execution flow.
- Use `impact` before discussing refactoring.
- Use `affected` when recommending regression tests.
- Do not rerun `codegraph init` unless the `.codegraph` directory has been removed.