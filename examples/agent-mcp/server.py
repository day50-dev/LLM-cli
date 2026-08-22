#!/usr/bin/env python3
"""
A stdio MCP server with the four tools an agentic coding loop needs:

    run_bash_command   read_file   write_file   question_user

Stdlib only. Point llcat at it and you have a coding agent:

    llcat -mf examples/agent-mcp/mcp.json "some agentic task"

llcat runs a fresh copy of this process per tool call, so nothing persists
between them -- hence `cwd` on run_bash_command rather than `cd`. stdout is
the JSON-RPC channel, so question_user talks to /dev/tty instead.
"""

import json
import os
import subprocess
import sys

MAX_OUTPUT = 30000  # bytes of tool output handed back to the model
DEFAULT_READ_LIMIT = 2000  # lines


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------

def run_bash_command(command, cwd=None, timeout=120):
    proc = subprocess.run(
        ["bash", "-c", command],
        cwd=cwd or os.getcwd(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = ""
    if proc.stdout:
        out += proc.stdout
    if proc.stderr:
        out += ("\n" if out else "") + "[stderr]\n" + proc.stderr
    if proc.returncode != 0:
        out += f"\n[exit {proc.returncode}]"
    return out or "[no output]"


def read_file(path, offset=1, limit=DEFAULT_READ_LIMIT):
    """offset is a 1-based line number, matching how errors and diffs count."""
    with open(path, "r", errors="replace") as fh:
        lines = fh.readlines()

    start = max(1, int(offset)) - 1
    chunk = lines[start:start + int(limit)]
    if not chunk:
        return f"[{path} has {len(lines)} lines; offset {offset} is past the end]"

    # Line numbers are not decoration: they are how the model anchors an edit.
    body = "".join(f"{start + i + 1}\t{line}" for i, line in enumerate(chunk))
    tail = ""
    if start + len(chunk) < len(lines):
        tail = f"\n[truncated at line {start + len(chunk)} of {len(lines)}]"
    return body + tail


def write_file(path, content, offset=None, limit=None):
    """The complement of read_file: the same window, written instead of read.

    Omit offset and limit for a whole-file write; limit=0 inserts.
    """
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)

    new = content.splitlines(keepends=True)
    if new and not new[-1].endswith("\n"):
        new[-1] += "\n"

    if offset is None:
        existed = os.path.exists(path)
        with open(path, "w") as fh:
            fh.write(content)
        verb = "Overwrote" if existed else "Wrote"
        return f"{verb} {path} ({len(new)} lines)"

    with open(path, "r", errors="replace") as fh:
        lines = fh.readlines()

    start = max(1, int(offset)) - 1
    if start > len(lines):
        return (f"[offset {offset} is past the end of {path}, which has "
                f"{len(lines)} lines; nothing written]")
    # A missing limit means "to the end", mirroring a read that ran off the end.
    end = len(lines) if limit is None else min(len(lines), start + int(limit))

    with open(path, "w") as fh:
        fh.writelines(lines[:start] + new + lines[end:])

    total = len(lines) - (end - start) + len(new)
    n = f"{len(new)} line" + ("" if len(new) == 1 else "s")
    if end == start:
        what = f"Inserted {n} before line {offset} of {path}"
    else:
        what = f"Replaced lines {start + 1}-{end} of {path} with {n}"
    return f"{what} (now {total} lines)"


def question_user(question, options=None):
    """Ask the human. stdin is the JSON-RPC pipe, so use the terminal directly."""
    try:
        tty = open("/dev/tty", "r+")
    except OSError:
        return "[no terminal available; the user could not be asked]"

    with tty:
        tty.write("\n" + question + "\n")
        if options:
            for i, opt in enumerate(options, 1):
                tty.write(f"  {i}) {opt}\n")
        tty.write("> ")
        tty.flush()
        answer = tty.readline().strip()

    if options and answer.isdigit() and 1 <= int(answer) <= len(options):
        answer = options[int(answer) - 1]
    return answer or "[the user gave no answer]"


TOOLS = [
    {
        "name": "run_bash_command",
        "description": (
            "Run a bash command and return its combined output. Each call runs in a "
            "fresh shell: cd, exported variables and background jobs do NOT persist "
            "between calls, so pass cwd instead of running cd. Use this for search "
            "(rg, grep, find), for tests, and for anything git."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to run."},
                "cwd": {"type": "string", "description": "Directory to run in. Defaults to the server's working directory."},
                "timeout": {"type": "integer", "description": "Seconds before the command is killed. Default 120."},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a text file, returned as tab-separated line-number/content pairs. "
            "Reads from line `offset` for `limit` lines so you can page through a large "
            "file instead of pulling all of it into context."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file."},
                "offset": {"type": "integer", "description": "1-based line to start at. Default 1."},
                "limit": {"type": "integer", "description": f"Number of lines to read. Default {DEFAULT_READ_LIMIT}."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write lines to a file, creating parent directories as needed. This is the "
            "complement of read_file and takes the same offset/limit window: reading a "
            "range, changing it, and writing it back with the same offset and limit "
            "replaces exactly that range and leaves the rest of the file alone. Omit "
            "offset and limit to replace the whole file. Use limit 0 to insert before "
            "`offset` without replacing anything. Line numbers shift as soon as you "
            "write, so re-read before making a second edit to the same file."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file."},
                "content": {"type": "string", "description": "The lines to write into the window."},
                "offset": {
                    "type": "integer",
                    "description": "1-based line to start writing at. Omit to replace the whole file.",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Number of existing lines the content replaces. 0 inserts without "
                        "replacing. Omitted with an offset means replace to end of file."
                    ),
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "question_user",
        "description": (
            "Ask the human a question and wait for their typed answer. Use this when a "
            "choice is genuinely theirs to make -- an ambiguous requirement, a "
            "destructive action, a missing credential -- not for things you can "
            "determine by reading the code."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to put to the user."},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional choices; the user may answer by number.",
                },
            },
            "required": ["question"],
        },
    },
]

HANDLERS = {
    "run_bash_command": run_bash_command,
    "read_file": read_file,
    "write_file": write_file,
    "question_user": question_user,
}


# --------------------------------------------------------------------------
# JSON-RPC plumbing
# --------------------------------------------------------------------------

def dispatch(name, arguments):
    handler = HANDLERS.get(name)
    if handler is None:
        return f"[no such tool: {name}]", True
    try:
        text = handler(**(arguments or {}))
        is_error = False
    except subprocess.TimeoutExpired:
        text, is_error = "[command timed out]", True
    except Exception as e:
        text, is_error = f"[{type(e).__name__}: {e}]", True

    if len(text) > MAX_OUTPUT:
        half = MAX_OUTPUT // 2
        text = text[:half] + "\n...[output truncated]...\n" + text[-half:]
    return text, is_error


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue

        method, id = msg.get("method"), msg.get("id")
        if id is None:  # a notification; nothing to answer
            continue

        if method == "initialize":
            result = {
                "protocolVersion": msg.get("params", {}).get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "agent-mcp", "version": "1.0"},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = msg.get("params", {})
            text, is_error = dispatch(params.get("name"), params.get("arguments"))
            result = {"content": [{"type": "text", "text": text}], "isError": is_error}
        elif method in ("prompts/list", "resources/list"):
            result = {method.split("/")[0]: []}
        else:
            print(json.dumps({
                "jsonrpc": "2.0", "id": id,
                "error": {"code": -32601, "message": f"unknown method: {method}"},
            }), flush=True)
            continue

        print(json.dumps({"jsonrpc": "2.0", "id": id, "result": result}), flush=True)


if __name__ == "__main__":
    main()
