# Getting started

`bhoonidhi-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io)
server. An MCP client launches it as a subprocess and talks to it over stdin and
stdout, so every setup comes down to one thing: **run this command.**

Phase 1 is read-only and needs no login.

## Install

```shell
pip install bhoonidhi-mcp
```

This installs the `bhoonidhi-mcp` command that MCP clients launch.

!!! tip "Use an absolute path for GUI clients"
    Desktop apps often don't inherit your shell's `PATH`. If a client can't find
    the server, point it at the absolute path to the installed binary
    (for example the one inside your virtualenv's `bin/`) instead of the bare
    `bhoonidhi-mcp` name.

## Check it runs

Before wiring a real client, confirm the server handshakes with the official
[MCP Inspector](https://github.com/modelcontextprotocol/inspector) — a browser UI
where you can click each tool and watch the live responses:

```shell
npx @modelcontextprotocol/inspector bhoonidhi-mcp
```

## Wire your client

=== "Claude Code"

    Register the server with the `claude` CLI:

    ```shell
    claude mcp add bhoonidhi -- bhoonidhi-mcp
    ```

    Inside a session, `/mcp` lists it as connected. Run the command inside a
    project directory to write a local `.mcp.json`, or add `--scope user` for a
    global registration.

=== "OpenCode"

    Add a local server block to `~/.config/opencode/opencode.json`, then restart:

    ```json
    {
      "$schema": "https://opencode.ai/config.json",
      "mcp": {
        "bhoonidhi": {
          "type": "local",
          "command": ["bhoonidhi-mcp"],
          "enabled": true
        }
      }
    }
    ```

=== "Claude Desktop"

    Edit `claude_desktop_config.json` (create it if missing), then fully quit and
    relaunch. Tools appear under the plug icon:

    ```json
    {
      "mcpServers": {
        "bhoonidhi": {
          "command": "bhoonidhi-mcp",
          "args": []
        }
      }
    }
    ```

=== "Any stdio client"

    The same shape works across MCP clients — a named server with a command and
    empty args:

    ```json
    {
      "mcpServers": {
        "bhoonidhi": {
          "command": "bhoonidhi-mcp",
          "args": []
        }
      }
    }
    ```

## Try it

Once connected, ask the agent something that needs the portal:

> Find Sentinel-2 scenes over Shillong from the first two weeks of January 2024.

The agent resolves "Shillong" to a bounding box, matches "Sentinel-2" to the
portal's platform tokens, runs the live search, and reports which results are
actually downloadable. See [Tools](tools.md) for what each call does.

!!! note "Live dependencies"
    Searches hit the real Bhoonidhi portal and a geocoder, so the first call in a
    session takes a second or two and needs network access. No credentials are
    required — Phase 1 is read-only.
