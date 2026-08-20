# MCP

No MCP servers are configured or required for this repository (no `.mcp.json`,
no `.vscode/mcp.json`). Development needs only a Python interpreter.

## Natural fit, if ever wanted

`napmem_retrieval_agent.py`'s tool surface (`search_memory_pyramid`,
`inspect_provenance`, `get_topic_track`, `compute_context_budget_savings`) is
already shaped like an MCP toolset. Exposing it as a stdio MCP server would
let any MCP client query the pyramid directly; document the server here and
add `.mcp.json` when that happens.
