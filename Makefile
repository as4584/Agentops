# Agentop Test Makefile — grouped per-domain test targets
# Usage: make test-all | make test-agents | make test-coverage

PYTEST = python -m pytest
PYTEST_OPTS = --tb=short -q --no-header
NO_COV = --no-cov

# ─── Full suites ──────────────────────────────────────────────────────────────

.PHONY: test
test:
	$(PYTEST) backend/tests/ deerflow/tests/ $(PYTEST_OPTS) $(NO_COV)

.PHONY: test-all
test-all:
	$(PYTEST) backend/tests/ deerflow/tests/ $(PYTEST_OPTS)

.PHONY: test-coverage
test-coverage:
	$(PYTEST) backend/tests/ deerflow/tests/ $(PYTEST_OPTS) \
	  --cov=backend --cov=deerflow \
	  --cov-report=term-missing \
	  --cov-report=html:htmlcov
	@echo "HTML report: htmlcov/index.html"

# ─── Domain groups ────────────────────────────────────────────────────────────

.PHONY: test-gateway
test-gateway:
	@echo "=== gateway ==="
	$(PYTEST) -m gateway --cov=backend/gateway --cov=backend/routes \
	  --cov-report=term-missing $(PYTEST_OPTS)

.PHONY: test-agents
test-agents:
	@echo "=== agents ==="
	$(PYTEST) -m agents --cov=backend/agents \
	  --cov-report=term-missing $(PYTEST_OPTS)

.PHONY: test-tools
test-tools:
	@echo "=== tools ==="
	$(PYTEST) -m tools --cov=backend/tools \
	  --cov-report=term-missing $(PYTEST_OPTS)

.PHONY: test-ml
test-ml:
	@echo "=== ml ==="
	$(PYTEST) -m ml --cov=backend/ml \
	  --cov-report=term-missing $(PYTEST_OPTS)

.PHONY: test-content
test-content:
	@echo "=== content ==="
	$(PYTEST) backend/tests/test_content_agents.py \
	  --cov=backend/content --cov-report=term-missing $(PYTEST_OPTS)

.PHONY: test-webgen
test-webgen:
	@echo "=== webgen ==="
	$(PYTEST) -m webgen --cov=backend/webgen \
	  --cov-report=term-missing $(PYTEST_OPTS)

.PHONY: test-deerflow
test-deerflow:
	@echo "=== deerflow ==="
	$(PYTEST) -m deerflow --cov=deerflow \
	  --cov-report=term-missing $(PYTEST_OPTS)

.PHONY: test-middleware
test-middleware:
	@echo "=== middleware ==="
	$(PYTEST) -m middleware --cov=backend/middleware --cov=deerflow/middleware \
	  --cov-report=term-missing $(PYTEST_OPTS)

.PHONY: test-memory
test-memory:
	@echo "=== memory ==="
	$(PYTEST) -m memory --cov=backend/memory \
	  --cov-report=term-missing $(PYTEST_OPTS)

.PHONY: test-models
test-models:
	@echo "=== models ==="
	$(PYTEST) -m models --cov=backend/models \
	  --cov-report=term-missing $(PYTEST_OPTS)

.PHONY: test-mcp
test-mcp:
	@echo "=== mcp ==="
	$(PYTEST) -m mcp --cov=backend/mcp \
	  --cov-report=term-missing $(PYTEST_OPTS)

.PHONY: test-skills
test-skills:
	@echo "=== skills ==="
	$(PYTEST) -m skills --cov=backend/skills \
	  --cov-report=term-missing $(PYTEST_OPTS)

.PHONY: test-security
test-security:
	@echo "=== security ==="
	$(PYTEST) backend/tests/test_security_agent.py \
	  --cov=backend/tools --cov=backend/agents \
	  --cov-report=term-missing $(PYTEST_OPTS)

# ─── All groups summary (no coverage, just pass/fail) ─────────────────────────

.PHONY: test-groups
test-groups:
	@for group in gateway agents tools ml webgen browser mcp middleware memory models deerflow skills; do \
	  echo ""; \
	  echo "=== $$group ==="; \
	  $(PYTEST) -m $$group --tb=no $(NO_COV) --no-header -q 2>&1 | tail -2; \
	done

# ─── Kubernetes deploy ────────────────────────────────────────────────────────
# Run these from WSL2. Requires docker + kubectl on PATH.

.PHONY: k8s-secret
k8s-secret:
	@echo "Creating/updating agentop-env secret from .env..."
	kubectl create secret generic agentop-env \
	  --from-env-file=.env \
	  -n agent-ops \
	  --dry-run=client -o yaml | kubectl apply -f -

.PHONY: k8s-build
k8s-build:
	@echo "Building agentop/backend:latest..."
	docker build -t agentop/backend:latest .

.PHONY: k8s-load
k8s-load:
	@echo "Loading image into cluster (Docker Desktop K8s — image shared automatically)..."
	@echo "If using kind:     kind load docker-image agentop/backend:latest"
	@echo "If using minikube: minikube image load agentop/backend:latest"
	@echo "Docker Desktop: no load step needed — daemon is shared."

.PHONY: k8s-apply
k8s-apply:
	kubectl apply -f k8s/backend/deployment.yaml
	kubectl apply -f k8s/discord-bot/deployment.yaml

.PHONY: k8s-deploy
k8s-deploy: k8s-build k8s-secret k8s-apply
	@echo "Waiting for rollout..."
	kubectl rollout restart deployment/agentop-backend -n agent-ops
	kubectl rollout status deployment/agentop-backend -n agent-ops --timeout=120s
	@echo ""
	@echo "Done. Both services in K8s:"
	@echo "  agentop-backend  → http://agentop-backend.agent-ops:8000"
	@echo "  discord-bot      → always-up, now connected"

.PHONY: k8s-logs
k8s-logs:
	kubectl logs -n agent-ops -l app=agentop-backend -f

.PHONY: k8s-status
k8s-status:
	kubectl get pods -n agent-ops
	@echo ""
	kubectl get svc -n agent-ops

.PHONY: k8s-dashboard
k8s-dashboard:
	@echo "Port-forwarding backend to localhost:8000..."
	kubectl port-forward -n agent-ops svc/agentop-backend 8000:8000

# ─── CI gate (mirrors CLAUDE.md requirements) ─────────────────────────────────

.PHONY: ci
ci: lint typecheck test-coverage

.PHONY: lint
lint:
	ruff check backend deerflow
	ruff format --check backend deerflow

.PHONY: typecheck
typecheck:
	mypy backend deerflow --ignore-missing-imports

.PHONY: help
help:
	@echo "Agentop Targets"
	@echo "──────────────────────────────────────────────────"
	@echo "  make k8s-deploy     Build image + sync secret + deploy to K8s"
	@echo "  make k8s-logs       Tail backend pod logs"
	@echo "  make k8s-status     Show all pods + services"
	@echo "  make k8s-dashboard  Port-forward backend to localhost:8000"
	@echo ""
	@echo "Test Targets"
	@echo "──────────────────────────────────────────────────"
	@echo "  make test           All tests, no coverage"
	@echo "  make test-all       All tests, with coverage"
	@echo "  make test-coverage  All tests, HTML + term report"
	@echo "  make test-groups    Per-group pass/fail summary"
	@echo ""
	@echo "  make test-gateway   Gateway + routes coverage"
	@echo "  make test-agents    Agent definitions coverage"
	@echo "  make test-tools     Native tools coverage"
	@echo "  make test-ml        ML modules coverage"
	@echo "  make test-content   Content pipeline coverage"
	@echo "  make test-webgen    Webgen pipeline coverage"
	@echo "  make test-deerflow  Deerflow coverage"
	@echo "  make test-middleware Middleware coverage"
	@echo "  make test-memory    Memory store coverage"
	@echo "  make test-models    Pydantic models coverage"
	@echo "  make test-mcp       MCP bridge coverage"
	@echo "  make test-skills    Skill registry coverage"
	@echo "  make test-security  Security agent coverage"
	@echo ""
	@echo "  make ci             lint + typecheck + coverage"
