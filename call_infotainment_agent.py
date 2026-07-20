#!/usr/bin/env python3
"""
call_infotainment_agent.py

CLI client for the Infotainment A2A agent.

Example:
    uv run python call_infotainment_agent.py \
        --task "baby song" \
        --endpoint http://localhost:8004
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Call the Infotainment A2A agent."
    )

    parser.add_argument(
        "--task",
        required=True,
        help="Natural language request."
    )

    parser.add_argument(
        "--endpoint",
        default=os.environ.get(
            "INFOTAINMENT_A2A_URL",
            "http://localhost:8004",
        ),
        help="A2A endpoint."
    )

    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENAI_API_KEY"),
    )

    parser.add_argument(
        "--base-url",
        default=os.environ.get("OPENAI_BASE_URL"),
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
    )

    return parser.parse_args(argv)


def build_request(args):
    metadata = {}

    if args.api_key:
        metadata["OPENAI_API_KEY"] = args.api_key

    if args.base_url:
        metadata["OPENAI_BASE_URL"] = args.base_url

    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "user",
                "parts": [
                    {
                        "kind": "text",
                        "text": args.task,
                    }
                ],
                "metadata": metadata,
            }
        },
    }


def call_agent(args):
    body = build_request(args)

    request = urllib.request.Request(
        args.endpoint.rstrip("/") + "/",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=args.timeout,
    ) as response:
        return json.loads(response.read().decode())


def extract_result(response):
    # JSON-RPC error
    if "error" in response:
        raise RuntimeError(
            json.dumps(response["error"], indent=2)
        )

    result = response.get("result")

    if result is None:
        raise RuntimeError(
            f"No result in response:\n{json.dumps(response, indent=2)}"
        )

    # Agent returned {parts:[...]}
    if isinstance(result, dict):
        parts = result.get("parts")

        if parts:
            for part in parts:
                root = part.get("root", part)

                if root.get("kind") == "text":
                    try:
                        return json.loads(root["text"])
                    except Exception:
                        return {
                            "success": True,
                            "message": root["text"],
                            "data": {},
                        }

    # Agent directly returned desired payload
    if isinstance(result, dict) and "success" in result:
        return result

    raise RuntimeError(
        f"Unknown response format:\n{json.dumps(response, indent=2)}"
    )


def main(argv=None):
    args = parse_args(argv)

    try:
        response = call_agent(args)
        result = extract_result(response)

    except urllib.error.URLError as e:
        result = {
            "success": False,
            "message": f"Connection error: {e}",
            "data": {},
        }
        print(json.dumps(result))
        return 2

    except Exception as e:
        result = {
            "success": False,
            "message": str(e),
            "data": {},
        }
        print(json.dumps(result))
        return 2

    print(json.dumps(result))

    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())