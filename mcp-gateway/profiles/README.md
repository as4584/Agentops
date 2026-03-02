# profiles/ — Per-agent MCP tool permission profiles
# ----------------------------------------------------
# Each YAML file in this directory defines which MCP servers and tools
# a specific Agentop agent is allowed to call through the gateway.
#
# The MCPBridge validates tool_permissions at the Agentop tool layer
# (see backend/tools/__init__.py). These profile files serve as
# documentation and can be used to configure profile-based gateway runs:
#
#   DOCKER_MCP_IN_CONTAINER=1 docker mcp gateway run --profile soul_core --port 8812
#
# Profile format:
#   servers:
#     - name: <server>
#       tools: [<tool>, ...]   # empty list = all tools for this server

# ── soul_core ─────────────────────────────────────────────────────
# Profile: soul_core
# Impact: CRITICAL
# Rationale: Soul needs broad read access for reflection + governance.
#             GitHub for org/repo inspection. Filesystem for docs.
#             Limited no-write tools to prevent unilateral mutation.

# ── devops_agent ──────────────────────────────────────────────────
# Profile: devops_agent
# Impact: HIGH
# Rationale: Full GitHub, Docker container management, time.

# ── monitor_agent ─────────────────────────────────────────────────
# Profile: monitor_agent
# Impact: LOW (read-only observer)
# Rationale: Fetch (HTTP probing), Docker (container status), time.

# ── self_healer_agent ─────────────────────────────────────────────
# Profile: self_healer_agent
# Impact: HIGH (can restart containers)
# Rationale: Docker with restart permission. Read-only on everything else.

# ── code_review_agent ─────────────────────────────────────────────
# Profile: code_review_agent
# Impact: MEDIUM
# Rationale: GitHub (diff/PR/code search), Filesystem (read source).

# ── security_agent ────────────────────────────────────────────────
# Profile: security_agent
# Impact: MEDIUM (EXCLUSIVELY READ-ONLY)
# Rationale: GitHub (code search for secrets), Filesystem (scan files).

# ── data_agent ────────────────────────────────────────────────────
# Profile: data_agent
# Impact: MEDIUM
# Rationale: SQLite (read-only queries), Filesystem (pipeline configs).

# ── comms_agent ───────────────────────────────────────────────────
# Profile: comms_agent
# Impact: MEDIUM
# Rationale: Slack (messaging), Fetch (integrations), Time (timestamps).

# ── cs_agent ──────────────────────────────────────────────────────
# Profile: cs_agent
# Impact: LOW
# Rationale: Filesystem (knowledge base), Time (response timestamps).

# ── it_agent ──────────────────────────────────────────────────────
# Profile: it_agent
# Impact: HIGH
# Rationale: Filesystem (infra configs), Docker (container status/logs), Time.

# ── knowledge_agent ───────────────────────────────────────────────
# Profile: knowledge_agent
# Impact: MEDIUM
# Rationale: Filesystem (docs), Fetch (web retrieval for knowledge).
#
# See each agent's tool_permissions in backend/agents/__init__.py for
# the authoritative list of allowed mcp_* tools.
