"""
Scan a C codebase with codegraph, then ask OpenAI questions about it.

Setup (run once in your WSL2 project):
    pip install openai python-dotenv
    cd code_base_c_test
    codegraph init          # builds .codegraph/ index

Usage:
    python ask_c_codebase.py "How does the auth module validate a token?"
"""

import os
import sys
import subprocess
import json

from dotenv import load_dotenv
from openai import OpenAI

# --- Config ---
PROJECT_DIR = "code_base_c_test"   # your C codebase folder

load_dotenv()  # reads OPENAI_API_KEY from .env
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def codegraph_explore(question: str) -> str:
    """Ask codegraph's explore command for relevant C source + call context."""
    result = subprocess.run(
        ["codegraph", "explore", question],
        capture_output=True,
        text=True,
        cwd=PROJECT_DIR,
    )
    if result.returncode != 0:
        raise RuntimeError(f"codegraph error: {result.stderr.strip()}")
    if not result.stdout.strip():
        raise RuntimeError("codegraph returned no output — is the project indexed? Run `codegraph init`.")
    return result.stdout


def ask_openai(question: str, context: str) -> str:
    """Send the codegraph context + question to OpenAI and return the answer."""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a C code assistant. Use the provided code graph context "
                    "(source snippets, call paths, symbols) to answer the user's question "
                    "about the codebase. If the context doesn't contain enough information, "
                    "say so instead of guessing."
                ),
            },
            {
                "role": "user",
                "content": f"Codebase context:\n{context}\n\nQuestion: {question}",
            },
        ],
    )
    return response.choices[0].message.content


def main():
    if len(sys.argv) < 2:
        print('Usage: python ask_c_codebase.py "your question here"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])

    print(f"Exploring codebase for: {question}\n")
    context = codegraph_explore(question)

    print("Asking OpenAI...\n")
    answer = ask_openai(question, context)

    print("=== Answer ===")
    print(answer)


if __name__ == "__main__":
    main()