# Agentop Orchestrator — VS Code Extension

Routes your VS Code Copilot Chat (`@agentop`) directly to the Agentop multi-agent backend.  
Every agent in the fleet is accessible via a slash command.

---

## Requirements

- Agentop backend running at `http://localhost:8000` (`python3 app.py`)
- Ollama running at `http://localhost:11434` with `llama3.2` pulled
- VS Code 1.90+ with GitHub Copilot Chat

---

## Usage

Open the VS Code Chat panel (`Ctrl+Alt+I`) and start a message with `@agentop`.

| Slash Command | Backend Agent       | Use For                                      |
|---------------|---------------------|----------------------------------------------|
| `/soul`       | `soul_core`         | Cluster governance, goals, reflection, trust |
| `/devops`     | `devops_agent`      | Git ops, deployments, CI/CD pipeline status  |
| `/monitor`    | `monitor_agent`     | Health checks, log tailing, metrics          |
| `/security`   | `security_agent`    | Secret scanning, CVE alerts                  |
| `/review`     | `code_review_agent` | Diff review, architectural invariant checks  |
| `/data`       | `data_agent`        | Read-only DB queries, schema drift detection |
| `/comms`      | `comms_agent`       | Outbound webhooks, incident announcements    |
| `/it`         | `it_agent`          | Infrastructure diagnostics, shell commands   |
| `/cs`         | `cs_agent`          | Customer support, knowledge base lookup      |
| *(default)*   | `knowledge_agent`   | General semantic Q&A over project docs       |

If no slash command is given, the extension automatically detects intent from keywords in your prompt and routes to the most relevant agent.

---

## Examples

```
@agentop /soul What are our current cluster goals?
@agentop /devops Show me the last 10 git commits
@agentop /security Scan backend/config.py for exposed secrets
@agentop /monitor Is the backend service healthy?
@agentop /review What does the latest diff change architecturally?
@agentop What is the knowledge agent's memory namespace?
```

---

## Command Palette Commands

| Command                              | Description                                   |
|--------------------------------------|-----------------------------------------------|
| `Agentop: Open Dashboard`            | Open the Next.js dashboard in a browser       |
| `Agentop: List Agents`               | Quick-pick of all registered agents           |
| `Agentop: Trigger Soul Reflection`   | Prompt soul_core to reflect on cluster state  |

---

## Configuration

| Setting                  | Default                   | Description                                 |
|--------------------------|---------------------------|---------------------------------------------|
| `agentop.backendUrl`     | `http://localhost:8000`   | Agentop FastAPI backend URL                 |
| `agentop.defaultAgent`   | `knowledge_agent`         | Agent used when no slash command given      |
| `agentop.streamResponses`| `true`                    | Stream responses into chat                  |

Set in VS Code Settings (`Ctrl+,`) under **Agentop**.

---

## Development

```bash
# from this directory
npm install
npm run compile          # one-off compile
npm run watch            # watch mode

# Press F5 in VS Code to launch the Extension Development Host
```

Place a `128×128` PNG at `assets/agentop.png` to show a chat participant icon.

---

## Architecture

```
VS Code Chat (@agentop)
    │  slash command or keyword intent detection
    ▼
extension.ts — createHandler()
    │  POST /chat { agent_id, message }
    ▼
AgentopClient (agentClient.ts)
    │  HTTP → localhost:8000
    ▼
FastAPI Backend → LangGraph Orchestrator → Agent → Tool Layer → Ollama
    │
    ◄─ ChatResponse { agent_id, message, drift_status }
    │
    ▼
stream.markdown(formatted response)
```

The extension is a **thin routing layer only** — no agent logic lives here.  
All memory, DriftGuard enforcement, tool execution, and LLM calls happen in the backend.
