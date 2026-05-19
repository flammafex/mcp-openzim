# OpenZIM MCP Server

`openzim-mcp` is an MCP server for reading and searching ZIM archives.

This fork keeps the same package name but is intentionally opinionated for a
single-user deployment:

- bare-metal, not Docker-first
- `systemd`-managed HTTP service
- simple mode as the default operating model
- one persistent Wikipedia archive at a known path
- reduced prompt surface: `/research` only

Current fork version: `2.0.1`

Maintainer: `sibyl`

## What This Fork Changes

Compared with upstream, this fork is optimized for a narrow and stable setup.

- simple mode still exposes `zim_query`
- simple mode exposes only the `/research` MCP prompt
- `summarize` and `explore` prompts are not registered
- when a client mistakenly passes an entry path into `zim_file_path`, simple
  mode treats that as a slot error and falls back to the single loaded archive

That last point matters for small models and weak MCP clients. A payload like
this:

```json
{
  "compact": true,
  "query": "summary of A/Marcellina_(gnostic)",
  "zim_file_path": "A/Marcellina_(gnostic)"
}
```

now resolves against the real archive instead of treating
`A/Marcellina_(gnostic)` as a filesystem path.

## Intended Deployment

This fork is written around a single persistent archive:

```text
/srv/zim/wikipedia_en_all_maxi_2022-05.zim
```

and a local HTTP service bound to loopback, typically behind a reverse proxy.

Example service command:

```bash
uv run openzim-mcp --mode simple --transport http --host 127.0.0.1 --port 3338 /srv/zim
```

## Features Kept In This Fork

- `zim_query` natural-language interface
- advanced mode codepath and tooling
- HTTP transport
- search, article retrieval, structure, links, title lookup
- compact simple-mode rendering
- single registered MCP prompt: `/research`

## Features Intentionally De-Emphasized

- Docker-first deployment guidance
- broad multi-client prompt workflows
- prompt flows that require the caller to supply `zim_file_path`

The code still contains far more capability than this README emphasizes. The
difference is intentional: this document is for operating this fork, not for
advertising every upstream feature.

## Installation

Requirements:

- Python `3.12+`
- `uv`
- a readable directory containing your `.zim` files

Clone the repo:

```bash
git clone <your-fork-url>
cd openzim-mcp
```

Install dependencies:

```bash
uv sync
```

Run locally:

```bash
uv run openzim-mcp --mode simple /srv/zim
```

Run over HTTP:

```bash
uv run openzim-mcp --mode simple --transport http --host 127.0.0.1 --port 3338 /srv/zim
```

## Bare-Metal `systemd` Deployment

This fork is expected to run directly on a host, not in a container.

Example unit:

```ini
[Unit]
Description=OpenZIM MCP Server
After=network-online.target
Wants=network-online.target

[Service]
User=openzim-mcp
Group=openzim-mcp
WorkingDirectory=/opt/openzim-mcp/app
EnvironmentFile=/etc/openzim-mcp/openzim-mcp.env

ExecStart=/var/lib/openzim-mcp/.local/bin/uv run openzim-mcp --mode simple --transport http --host 127.0.0.1 --port 3338 /srv/zim

Restart=always
RestartSec=5

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/srv/zim /opt/openzim-mcp
ReadWritePaths=/var/lib/openzim-mcp
RestrictSUIDSGID=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now openzim-mcp
sudo systemctl status openzim-mcp
```

## Updating The Deployment

For this setup, do not copy local virtual environments into the server tree.

Deploy source only:

- copy or pull the repo into `/opt/openzim-mcp/app`
- keep `.venv` off the server copy
- rebuild the environment on the target host with `uv sync`

Typical update flow:

```bash
sudo systemctl stop openzim-mcp
cd /opt/openzim-mcp/app
git pull
sudo -u openzim-mcp /var/lib/openzim-mcp/.local/bin/uv sync
sudo systemctl start openzim-mcp
```

If you are deploying by copying files rather than pulling on-host, replace the
whole app tree rather than pasting selected files over an existing checkout.

## MCP Surface In Simple Mode

Simple mode in this fork is intentionally small.

Tools:

- `zim_query`

Prompts:

- `/research`
- `/article`
- `/compare`
- `/timeline`
- `/map`

That is the interface you should expect clients to see.

All prompts are workflow macros over `zim_query`; they do not reference the
advanced-mode tools. They assume a single offline Wikipedia archive and tell
clients to omit `zim_file_path` so the server can auto-select the loaded
archive.

## Example Queries

These are the kinds of simple-mode requests this fork is tuned for:

- `tell me about Marcellina`
- `summary of A/Marcellina_(gnostic)`
- `show structure of Photosynthesis`
- `links in Ada Lovelace`
- `find article titled Hypatia`
- `search for gnosticism`

## Versioning

This fork now uses a normal release version:

- `2.0.1`

That replaces the upstream alpha train version that was present in this tree.

## Development Notes

Useful commands:

```bash
uv run pytest tests/test_server.py tests/test_simple_tools.py tests/test_prompts.py -q
uv run pytest -q
```

The fork-specific behavior currently pinned by tests includes:

- simple mode prompt registration
- entry-like `zim_file_path` fallback in single-archive mode
- reduced prompt surface
- Wikipedia-oriented simple-mode prompts over `zim_query`

## License

This repository remains under the existing project license unless you change it
separately.
