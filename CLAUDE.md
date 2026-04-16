## graphify

This project has a knowledge graph at `graphify-out/graph.json` (372 nodes, 902 edges, 32 communities).

**Before reading multiple files** to answer questions about architecture, call flow, or cross-file relationships, use `/graphify query "<question>"` first. The graph traversal returns the relevant subgraph in ~3,600 tokens instead of loading the full 24,500-word corpus (~32,700 tokens). That's a 9x reduction per query.

**How to use it:**
- `/graphify query "how does ticket creation work"` — BFS from matching nodes, broad context
- `/graphify query "how does WhatsApp reach the database" --dfs` — trace a specific path
- `/graphify path "WhatsApp Webhook" "Database Connection"` — shortest hop path
- `/graphify explain "Ticket Service Logic"` — full neighborhood of one community

**After making code changes**, run `/graphify --update` to refresh the graph incrementally (AST-only for code changes = 0 LLM tokens).

**Key communities to know:**
- `Ticket Service Logic` — core business logic for ticket lifecycle
- `LLM Message Classification` — Claude-powered WhatsApp triage
- `WhatsApp Webhook` → `WhatsApp Message Parsing` → `Ticket Service Logic` — the inbound message flow
- `Frontend API Client` + `Frontend UI Components` — the JS single-page app
- `Auth & Token Service` + `Auth Dependencies` — JWT auth stack

Graph built: 2026-04-15. Run `/graphify --update` after significant code changes.
