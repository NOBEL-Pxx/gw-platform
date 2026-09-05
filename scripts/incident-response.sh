#!/bin/bash
#==============================================================================
# Incident Response Toolkit — GravitationalWave Platform v4.37
# Quick-response commands for security incidents.
#
# Usage:
#   bash scripts/incident-response.sh isolate <service>
#   bash scripts/incident-response.sh snapshot-logs <service>
#   bash scripts/incident-response.sh block-ip <ip>
#   bash scripts/incident-response.sh emergency-stop
#   bash scripts/incident-response.sh status
#==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INCIDENT_DIR="${PROJECT_DIR}/docker-data/incidents"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

mkdir -p "${INCIDENT_DIR}"

# ── Notification ───────────────────────────────────────────────────────────
notify() {
  local level="$1"; shift
  local message="$*"

  echo -e "${RED}[INCIDENT:${level}]${NC} $message"

  # Send webhook if configured
  if [ -n "${NOTIFY_CMD:-}" ]; then
    eval "$NOTIFY_CMD" 2>/dev/null || true
  fi

  # Log to incident file
  local log_file="${INCIDENT_DIR}/incident_${TIMESTAMP}.log"
  echo "[$(date -Iseconds)] [$level] $message" >> "$log_file"
}

# ═══════════════════════════════════════════════════════════════════════════
#  COMMANDS
# ═══════════════════════════════════════════════════════════════════════════

cmd_isolate() {
  local service="$1"
  echo -e "${RED}Isolating service: $service${NC}"
  echo "This will disconnect $service from all networks."

  # Disconnect from all networks
  local networks
  networks=$(docker inspect "$service" --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>/dev/null)
  if [ -z "$networks" ]; then
    echo "Service not found or no networks: $service"
    exit 1
  fi

  for net in $networks; do
    echo "  Disconnecting from: $net"
    docker network disconnect "$net" "$service" 2>/dev/null || echo "  (already disconnected?)"
  done

  # Preserve container for forensics (don't remove)
  docker stop "$service" 2>/dev/null || true

  notify "CRITICAL" "Service isolated: $service (networks: $networks)"
  echo ""
  echo -e "${YELLOW}Container preserved for forensics. To reconnect:${NC}"
  for net in $networks; do
    echo "  docker network connect $net $service"
  done
  echo "  docker start $service"
}

cmd_snapshot_logs() {
  local service="$1"
  local logdir="${INCIDENT_DIR}/logs_${service}_${TIMESTAMP}"
  mkdir -p "$logdir"

  echo "Snapshotting logs for: $service"
  echo "Output: $logdir"

  # Docker logs
  docker logs "$service" --tail 10000 > "${logdir}/docker-logs.txt" 2>&1
  echo "  docker-logs.txt ($(wc -l < "${logdir}/docker-logs.txt") lines)"

  # Inspect container state
  docker inspect "$service" > "${logdir}/container-inspect.json" 2>&1
  echo "  container-inspect.json"

  # Network info
  docker exec "$service" netstat -tlnp 2>/dev/null > "${logdir}/netstat.txt" || echo "  (netstat not available)"
  docker exec "$service" ss -tlnp 2>/dev/null > "${logdir}/ss.txt" || echo "  (ss not available)"

  # Process list
  docker exec "$service" ps aux 2>/dev/null > "${logdir}/ps.txt" || echo "  (ps not available)"
  docker top "$service" > "${logdir}/processes.txt" 2>&1
  echo "  processes.txt"

  # Recent file changes
  docker exec "$service" find /app -mmin -60 -type f 2>/dev/null > "${logdir}/recent-changes.txt" || echo "  (find not available)"

  notify "INFO" "Logs snapshotted: $service → $logdir"
  echo ""
  echo -e "${GREEN}Log snapshot complete: $logdir${NC}"
}

cmd_block_ip() {
  local ip="$1"

  # Basic IP validation
  if ! echo "$ip" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo -e "${RED}Invalid IP address: $ip${NC}"
    exit 1
  fi

  echo -e "${RED}Blocking IP: $ip${NC}"

  # Add iptables rule (if running on host)
  if command -v iptables &>/dev/null; then
    iptables -A INPUT -s "$ip" -j DROP 2>/dev/null && echo "  iptables: blocked" || echo "  iptables: failed (need root)"
  fi

  # Add to nginx blocklist
  local nginx_blocklist="/etc/nginx/conf.d/blocked-ips.conf"
  echo "deny $ip;" >> "${INCIDENT_DIR}/blocked-ips.conf"
  echo "  Added to blocked-ips.conf"

  # Reload nginx if running
  if docker ps --format '{{.Names}}' | grep -q "^gw-frontend$"; then
    docker exec gw-frontend nginx -s reload 2>/dev/null && echo "  nginx: reloaded" || echo "  nginx: reload failed"
  fi

  notify "WARNING" "IP blocked: $ip"
}

cmd_emergency_stop() {
  echo ""
  echo -e "${RED}╔══════════════════════════════════════════════╗${NC}"
  echo -e "${RED}║  EMERGENCY STOP — PRESERVING DATA LAYER     ║${NC}"
  echo -e "${RED}╚══════════════════════════════════════════════╝${NC}"
  echo ""

  # Confirm
  echo -n "Stop ALL non-data services? This will preserve MongoDB and Elasticsearch. [yes/N]: "
  read -r confirm
  if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    return
  fi

  # Stop in reverse dependency order
  local app_services=("gw-frontend" "gw-mcp-server" "gw-pipeline" "gw-firefly" "gw-backend")

  for svc in "${app_services[@]}"; do
    if docker ps --format '{{.Names}}' | grep -q "^${svc}$"; then
      echo "  Stopping: $svc"
      docker stop "$svc" 2>/dev/null || echo "  (already stopped)"
    fi
  done

  notify "CRITICAL" "EMERGENCY STOP triggered — all app services stopped. Data layer preserved."

  echo ""
  echo -e "${YELLOW}Data layer preserved:${NC}"
  docker ps --format '{{.Names}} {{.Status}}' | grep -E "mongo|elasticsearch"
  echo ""
  echo -e "To restart: ${CYAN}docker compose -f docker-compose.yml up -d${NC}"
}

cmd_status() {
  echo ""
  echo "GW Platform — Security Status"
  echo "═══════════════════════════════════════"
  echo ""

  # Container security
  echo "Container Security:"
  docker ps --filter "name=gw-" --format "{{.Names}}" | while read c; do
    local user=$(docker inspect "$c" --format '{{.Config.User}}' 2>/dev/null)
    user="${user:-root}"
    local readonly=$(docker inspect "$c" --format '{{.HostConfig.ReadonlyRootfs}}' 2>/dev/null)
    readonly="${readonly:-false}"
    local secopt=$(docker inspect "$c" --format '{{.HostConfig.SecurityOpt}}' 2>/dev/null)
    secopt="${secopt:-none}"

    if [ "$user" = "root" ] || [ "$user" = "" ]; then
      echo -e "  ${RED}$c${NC}: user=root readonly=$readonly secopt=$secopt"
    else
      echo -e "  ${GREEN}$c${NC}: user=$user readonly=$readonly secopt=$secopt"
    fi
  done

  echo ""
  echo "Active Incidents:"
  ls "${INCIDENT_DIR}"/incident_*.log 2>/dev/null | tail -5 | while read f; do
    echo "  $(basename "$f")"
  done || echo "  (none)"

  echo ""
  echo "Blocked IPs:"
  cat "${INCIDENT_DIR}/blocked-ips.conf" 2>/dev/null || echo "  (none)"

  echo ""
  echo "Last Recovery Drill:"
  ls -t "${PROJECT_DIR}/docker-data/drill-results"/drill_*.log 2>/dev/null | head -1 | while read f; do
    echo "  $(basename "$f") — $(head -1 "$f")"
  done || echo "  (none)"
}

# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════
case "${1:-}" in
  isolate)
    [ -z "${2:-}" ] && { echo "Usage: $0 isolate <service>"; exit 1; }
    cmd_isolate "$2"
    ;;
  snapshot-logs|logs)
    [ -z "${2:-}" ] && { echo "Usage: $0 snapshot-logs <service>"; exit 1; }
    cmd_snapshot_logs "$2"
    ;;
  block-ip|block)
    [ -z "${2:-}" ] && { echo "Usage: $0 block-ip <ip>"; exit 1; }
    cmd_block_ip "$2"
    ;;
  emergency-stop|estop)
    cmd_emergency_stop
    ;;
  status|st)
    cmd_status
    ;;
  *)
    echo "GW Incident Response Toolkit v4.37"
    echo ""
    echo "Commands:"
    echo "  isolate <service>      Disconnect service from all networks"
    echo "  snapshot-logs <service> Export all logs for forensics"
    echo "  block-ip <ip>          Block an IP address"
    echo "  emergency-stop         Stop all app services, preserve data"
    echo "  status                 Show security status"
    echo ""
    echo "Incident log directory: ${INCIDENT_DIR}"
    ;;
esac
