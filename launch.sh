#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Agent N9er — Live Launch Script
# ============================================================
# Usage:
#   1. Copy .env.example → .env and fill in your keys
#   2. Run: chmod +x launch.sh && ./launch.sh
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════╗"
echo "  ║         AGENT N9ER — LAUNCH SEQ          ║"
echo "  ╚══════════════════════════════════════════╝"
echo -e "${NC}"

# ── Preflight checks ──────────────────────────────────────────

echo -e "${YELLOW}[PREFLIGHT]${NC} Checking requirements..."

if ! command -v docker &>/dev/null; then
    echo -e "${RED}[FAIL]${NC} Docker not found. Install: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker compose version &>/dev/null && ! docker-compose version &>/dev/null; then
    echo -e "${RED}[FAIL]${NC} Docker Compose not found."
    exit 1
fi

COMPOSE_CMD="docker compose"
if ! docker compose version &>/dev/null; then
    COMPOSE_CMD="docker-compose"
fi

if [ ! -f .env ]; then
    echo -e "${RED}[FAIL]${NC} No .env file found."
    echo -e "  Run: ${CYAN}cp .env.example .env${NC}"
    echo -e "  Then fill in your API keys and tokens."
    exit 1
fi

# ── Validate critical env vars ────────────────────────────────

source .env 2>/dev/null || true

MISSING=()
if [ -z "${FREELANCER_OAUTH_TOKEN:-}" ]; then MISSING+=("FREELANCER_OAUTH_TOKEN"); fi
if [ -z "${FREELANCER_USER_ID:-}" ]; then MISSING+=("FREELANCER_USER_ID"); fi
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then MISSING+=("TELEGRAM_BOT_TOKEN"); fi
if [ -z "${TELEGRAM_CHAT_ID:-}" ]; then MISSING+=("TELEGRAM_CHAT_ID"); fi

HAS_LLM=false
for key in OPENROUTER_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY AZURE_OPENAI_API_KEY GEMINI_API_KEY; do
    if [ -n "${!key:-}" ]; then HAS_LLM=true; break; fi
done
if [ "$HAS_LLM" = false ]; then MISSING+=("(at least one LLM API key)"); fi

if [ ${#MISSING[@]} -gt 0 ]; then
    echo -e "${YELLOW}[WARN]${NC} Missing env vars (system may run with limited functionality):"
    for m in "${MISSING[@]}"; do
        echo -e "  ${RED}•${NC} $m"
    done
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then exit 1; fi
fi

# ── Build ─────────────────────────────────────────────────────

echo ""
echo -e "${CYAN}[BUILD]${NC} Building all 15 services..."
$COMPOSE_CMD build --parallel 2>&1 | tail -5

# ── Launch ────────────────────────────────────────────────────

echo ""
echo -e "${CYAN}[LAUNCH]${NC} Starting services..."
$COMPOSE_CMD up -d

# ── Health check ──────────────────────────────────────────────

echo ""
echo -e "${CYAN}[HEALTH]${NC} Waiting for services to become healthy..."

SERVICES=(
    "normalization-service:8100"
    "ranking-engine:8200"
    "bidding-marketplace:8300"
    "agent-execution:8400"
    "reputation-ledger:8500"
    "recurring-engine:8600"
    "evaluator:8800"
    "prospector:8900"
    "orchestrator:9000"
    "billing:9200"
    "enterprise-tools:9300"
    "browser-service:8001"
    "simulation-engine:9100"
    "dashboard:3000"
)

MAX_WAIT=120
WAITED=0
ALL_HEALTHY=false

while [ $WAITED -lt $MAX_WAIT ]; do
    HEALTHY=0
    TOTAL=${#SERVICES[@]}
    for svc in "${SERVICES[@]}"; do
        NAME="${svc%%:*}"
        PORT="${svc##*:}"
        if $COMPOSE_CMD exec -T "$NAME" python -c "import urllib.request; urllib.request.urlopen('http://localhost:$PORT/health')" &>/dev/null 2>&1; then
            ((HEALTHY++))
        fi
    done

    if [ $HEALTHY -eq $TOTAL ]; then
        ALL_HEALTHY=true
        break
    fi

    echo -e "  ${YELLOW}${HEALTHY}/${TOTAL}${NC} healthy... (${WAITED}s)"
    sleep 5
    ((WAITED+=5))
done

echo ""
if [ "$ALL_HEALTHY" = true ]; then
    echo -e "${GREEN}[OK]${NC} All ${#SERVICES[@]} services healthy."
else
    echo -e "${YELLOW}[WARN]${NC} Some services not yet healthy after ${MAX_WAIT}s."
    echo -e "  Check: ${CYAN}$COMPOSE_CMD ps${NC}"
    echo -e "  Logs:  ${CYAN}$COMPOSE_CMD logs --tail 20 <service-name>${NC}"
fi

# ── Status report ─────────────────────────────────────────────

echo ""
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  AGENT N9ER IS LIVE${NC}"
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo ""
echo -e "  Dashboard:    ${CYAN}http://localhost:3000${NC}"
echo -e "  Orchestrator: ${CYAN}http://localhost:9000/docs${NC}"
echo -e "  Prospector:   ${CYAN}http://localhost:8900/docs${NC}"
echo ""
echo -e "  ${YELLOW}Active Systems:${NC}"
echo -e "    Auto-Scan:     ${GREEN}ON${NC}  (every ${SCAN_INTERVAL_SECONDS:-3600}s)"
echo -e "    Auto-Bid:      ${GREEN}ON${NC}  (${FREELANCER_MAX_BIDS_PER_MONTH:-45}/mo, ${FREELANCER_MAX_BIDS_PER_HOUR:-5}/hr)"
echo -e "    Auto-Reply:    ${GREEN}ON${NC}  (${AUTO_REPLY_DELAY_SECONDS:-30}s delay, ${AUTO_REPLY_MAX_PER_THREAD_HOUR:-3}/hr/thread)"
echo -e "    Quote Gen:     ${GREEN}ON${NC}  (auto-detect pricing questions)"
echo -e "    Telegram Cmds: ${GREEN}ON${NC}  (/override, /skip, /send)"
echo -e "    Ethics Screen: ${GREEN}ON${NC}  (pre-bid + pre-delivery)"
echo ""
echo -e "  ${YELLOW}Telegram Commands:${NC}"
echo -e "    /override <thread_id> <msg>  — send custom reply"
echo -e "    /skip <thread_id>            — cancel auto-reply"
echo -e "    /send <thread_id>            — send immediately"
echo ""
echo -e "  ${YELLOW}Useful Commands:${NC}"
echo -e "    $COMPOSE_CMD logs -f orchestrator    — watch main loop"
echo -e "    $COMPOSE_CMD logs -f prospector      — watch bids/messages"
echo -e "    $COMPOSE_CMD ps                       — service status"
echo -e "    $COMPOSE_CMD down                     — stop everything"
echo ""
