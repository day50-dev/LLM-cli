# agent-mcp — an agentic coding loop in one command

```shell
llcat -mf examples/agent-mcp/mcp.json "add a --version flag to hello.py and run it to confirm"
```

That's the whole thing. llcat already runs the control loop: it calls the tools
the model asks for, feeds the results back, and keeps going until the model
stops asking. One MCP server plus llcat is a coding agent.

`server.py` is that server — stdlib only, one file, four tools:

| tool | what it does |
|---|---|
| `run_bash_command` | run a command, get stdout/stderr and exit status |
| `read_file` | read a window of lines with `offset`/`limit`, numbered |
| `write_file` | write a window of lines with the same `offset`/`limit` |
| `question_user` | ask the human and block for their answer |

Search, listing, git and running tests all fall out of `run_bash_command`, so
there's no glob or grep tool. And because `write_file` takes the same window
`read_file` hands back, editing is just reading a range and writing it back —
no separate edit tool either. Omit the window for a whole-file write; pass
`limit: 0` to insert without replacing.

## Poking at it directly

With the `mcpcat` helper at the repo root:

```shell
./mcpcat init list | python3 examples/agent-mcp/server.py

./mcpcat init \
  call read_file  '{"path":"hello.py","offset":40,"limit":3}' \
  call write_file '{"path":"hello.py","offset":40,"limit":3,"content":"...new lines..."}' \
  | python3 examples/agent-mcp/server.py
```

## One thing to know

llcat starts a fresh copy of the server for each tool call, so nothing persists
between them — no shell cwd, no exported variables, no background jobs. That's
why `run_bash_command` takes a `cwd` instead of relying on `cd`, and why
`question_user` reads from `/dev/tty` rather than stdin.
