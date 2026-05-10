# Fork note

This is **[MacSiem's fork](https://github.com/MacSiem/openpets)** of
[alterhq/openpets](https://github.com/alterhq/openpets). The fork stays
in sync with upstream; **all Swift / native macOS code is theirs**, and
they did the heavy lifting (the desktop app, the MCP server, the IPC
plumbing, the OpenPetsKit Swift package).

What this fork adds, in a single subdirectory:

```
bridge/      — openpets-bridge: a small Python daemon that watches the
                on-disk session logs of multiple AI coding agents (Cowork,
                Codex CLI, Claude Code CLI) and forwards their activity
                to OpenPets via the documented `notify --thread <uuid>`
                workflow. Useful when an agent runtime does not natively
                call the `notify` MCP tool.
```

See [`bridge/README.md`](./bridge/README.md) for install / configure /
contribute. MIT licensed (same as upstream).

If you're looking for OpenPets itself — the desktop app, the MCP server,
the Swift package — install it from
[**alterhq's releases**](https://github.com/alterhq/openpets/releases/latest).
You don't need this fork. The bridge is opt-in extra glue on top.
