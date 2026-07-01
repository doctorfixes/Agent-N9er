#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Agent N9er — Start All Services via Supervisor
# Uses supervisord for auto-recovery of all 12 microservices.
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SUPERVISOR_CONF="${SCRIPT_DIR}/supervisord.conf"
SUPERVISOR_LOG_DIR="${SCRIPT_DIR}/logs"
SUPERVISOR_PIDFILE="${SCRIPT_DIR}/supervisord.pid"
SUPERVISOR_SOCKFILE="${SCRIPT_DIR}/supervisor.sock"

# ── Service definitions: name:port ──
declare -A SERVICES=(
    [orchestrator]=9000
    [normalization]=8100
    [ranking]=8200
    [marketplace]=8300
    [execution]=8700
    [reputation]=8500
    [recurring]=8600
    [evaluator]=8801
    [prospector]=8900
    [billing]=9200
    [bid_service]=9400
    [browser]=8000
    [enterprise_tools]=8401
    [agent_registry]=9500
)

echo "=== Agent N9er Service Launcher ==="
echo "Script dir: ${SCRIPT_DIR}"

# ── Ensure dependencies ──
if ! command -v supervisord &>/dev/null; then
    echo "Installing supervisor..."
    pip install supervisor -q
fi

mkdir -p "${SUPERVISOR_LOG_DIR}"

# ── Generate supervisor config ──
cat > "${SUPERVISOR_CONF}" << 'SUPER_HEAD'
[supervisord]
nodaemon=false
logfile=%(here)s/logs/supervisord.log
pidfile=%(here)s/supervisord.pid
childlogdir=%(here)s/logs
minfds=1024
nocleanup=true

[unix_http_server]
file=%(here)s/supervisor.sock
chmod=0700

[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix://%(here)s/supervisor.sock

[include]
files = %(here)s/supervisord.d/*.conf
SUPER_HEAD

mkdir -p "${SUPERVISOR_CONF%/*}/supervisord.d"

rm -f "${SUPERVISOR_CONF%/*}/supervisord.d"/*.conf

for name in "${!SERVICES[@]}"; do
    port="${SERVICES[$name]}"
    # Map service dir names to their main.py paths
    case "$name" in
        orchestrator)     dir="orchestrator" ;;
        normalization)    dir="normalization_service" ;;
        ranking)          dir="ranking_engine" ;;
        marketplace)      dir="bidding_marketplace" ;;
        execution)        dir="agent_execution" ;;
        reputation)       dir="reputation_ledger" ;;
        recurring)        dir="recurring_engine" ;;
        evaluator)        dir="evaluator_service" ;;
        prospector)       dir="prospector_service" ;;
        billing)          dir="billing_service" ;;
        bid_service)      dir="bid_service" ;;
        browser)          dir="browser_service" ;;
        enterprise_tools) dir="enterprise_tools" ;;
        agent_registry)   dir="agent_registry" ;;
        *)                dir="$name" ;;
    esac

    env_port_var=$(echo "${name}" | tr '[:lower:]' '[:upper:]')_PORT
    cat > "${SUPERVISOR_CONF%/*}/supervisord.d/${name}.conf" << SERVICE_CONF
[program:n9er-${name}]
command=python -m uvicorn main:app --host 0.0.0.0 --port ${port} --log-level info
directory=${SCRIPT_DIR}/${dir}
environment=${env_port_var}=${port}
autostart=true
autorestart=true
startretries=3
stopwaitsecs=10
stdout_logfile=${SUPERVISOR_LOG_DIR}/${name}.log
stderr_logfile=${SUPERVISOR_LOG_DIR}/${name}_err.log
stdout_logfile_maxbytes=10MB
stderr_logfile_maxbytes=10MB
SERVICE_CONF
    echo "  ✓ ${name} → :${port} (${dir}/main.py)"
done

# ── Kill any existing supervisord ──
if [ -f "${SUPERVISOR_PIDFILE}" ]; then
    OLD_PID=$(cat "${SUPERVISOR_PIDFILE}")
    if kill -0 "${OLD_PID}" 2>/dev/null; then
        echo "Stopping existing supervisord (PID ${OLD_PID})..."
        supervisorctl -c "${SUPERVISOR_CONF}" shutdown 2>/dev/null || kill "${OLD_PID}" 2>/dev/null || true
    fi
    rm -f "${SUPERVISOR_PIDFILE}"
fi
rm -f "${SUPERVISOR_SOCKFILE}"

# ── Start supervisor ──
echo ""
echo "Starting supervisord..."
supervisord -c "${SUPERVISOR_CONF}"
echo "supervisord started (PID $(cat "${SUPERVISOR_PIDFILE}"))"

# ── Wait for services ──
echo ""
echo "Waiting for services to come online..."
sleep 2

UP_COUNT=0
TOTAL=${#SERVICES[@]}
for name in "${!SERVICES[@]}"; do
    port="${SERVICES[$name]}"
    if curl -sf "http://localhost:${port}/health" >/dev/null 2>&1; then
        echo "  ✓ ${name} (:${port}) — HEALTHY"
        UP_COUNT=$((UP_COUNT + 1))
    else
        echo "  ✗ ${name} (:${port}) — DOWN"
    fi
done

echo ""
echo "=== ${UP_COUNT}/${TOTAL} services healthy ==="
echo ""
echo "Supervisor commands:"
echo "  supervisorctl -c ${SUPERVISOR_CONF} status"
echo "  supervisorctl -c ${SUPERVISOR_CONF} restart n9er-<name>"
echo "  supervisorctl -c ${SUPERVISOR_CONF} tail n9er-<name>"
echo ""
echo "Stop all: supervisorctl -c ${SUPERVISOR_CONF} shutdown"