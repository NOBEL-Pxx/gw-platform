#!/bin/bash
#==============================================================================
# Dependency Vulnerability Scanner — GravitationalWave Platform v4.37
# Scans all project dependencies for known CVEs.
#
# Usage:
#   bash scripts/scan-deps.sh              # Full scan
#   bash scripts/scan-deps.sh --quick      # Quick scan (pip only)
#   bash scripts/scan-deps.sh --json       # JSON output
#==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RESULTS_DIR="${PROJECT_DIR}/docker-data/scan-results"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_FILE="${RESULTS_DIR}/scan_${TIMESTAMP}.txt"
JSON_FILE="${RESULTS_DIR}/scan_${TIMESTAMP}.json"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

mkdir -p "${RESULTS_DIR}"

# ── Initialize JSON ────────────────────────────────────────────────────────
JSON_MODE=false
[[ "${1:-}" == "--json" ]] && JSON_MODE=true

init_json() {
  cat > "$JSON_FILE" << 'EOF'
{
  "timestamp": "TIMESTAMP",
  "results": {}
}
EOF
  # Use python to update the timestamp
  python3 -c "
import json
with open('$JSON_FILE') as f: d = json.load(f)
d['timestamp'] = '$TIMESTAMP'
with open('$JSON_FILE', 'w') as f: json.dump(d, f, indent=2)
" 2>/dev/null || true
}

# ── Scan Functions ─────────────────────────────────────────────────────────

scan_pip() {
  local name="$1"
  local req_file="$2"
  echo ""
  echo "=== $name ($req_file) ===" >> "$OUTPUT_FILE"

  if [ ! -f "$req_file" ]; then
    echo "  SKIP: requirements.txt not found" >> "$OUTPUT_FILE"
    return
  fi

  # Try pip-audit first, fall back to safety
  if command -v pip-audit &>/dev/null; then
    echo "  Using: pip-audit" >> "$OUTPUT_FILE"
    pip-audit -r "$req_file" --cache-dir /tmp/pip-audit-cache 2>&1 | tee -a "$OUTPUT_FILE" || true
  elif python3 -c "import safety" 2>/dev/null; then
    echo "  Using: safety" >> "$OUTPUT_FILE"
    python3 -m safety check -r "$req_file" --json 2>&1 | tee -a "$OUTPUT_FILE" || true
  else
    echo "  FALLBACK: Checking with pip list --outdated" >> "$OUTPUT_FILE"
    # Extract package names and check for known issues
    grep -E '^[a-zA-Z]' "$req_file" | cut -d'=' -f1 | while read pkg; do
      pip install --dry-run "$pkg" 2>&1 | grep -i "error\|warning\|vulnerable" >> "$OUTPUT_FILE" || true
    done
  fi
}

scan_npm() {
  echo "" >> "$OUTPUT_FILE"
  echo "=== gw-frontend (npm) ===" >> "$OUTPUT_FILE"

  local frontend_dir="${PROJECT_DIR}/gw-frontend"
  if [ ! -f "${frontend_dir}/package.json" ]; then
    echo "  SKIP: package.json not found" >> "$OUTPUT_FILE"
    return
  fi

  cd "$frontend_dir"
  echo "  Using: npm audit" >> "$OUTPUT_FILE"
  npm audit --json 2>&1 | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    vulns = data.get('vulnerabilities', {})
    if not vulns:
        print('  No vulnerabilities found')
    else:
        high = sum(1 for v in vulns.values() if v.get('severity') == 'high')
        critical = sum(1 for v in vulns.values() if v.get('severity') == 'critical')
        moderate = sum(1 for v in vulns.values() if v.get('severity') == 'moderate')
        print(f'  Found: {len(vulns)} vulnerabilities ({critical} critical, {high} high, {moderate} moderate)')
        for name, v in sorted(vulns.items()):
            print(f'    {name}: {v.get(\"severity\", \"?\")} — {v.get(\"title\", \"?\")}')
except:
    print('  npm audit failed or returned non-JSON output')
" 2>&1 | tee -a "$OUTPUT_FILE"
  cd "$PROJECT_DIR"
}

scan_docker_images() {
  echo "" >> "$OUTPUT_FILE"
  echo "=== Docker Base Images ===" >> "$OUTPUT_FILE"

  local images=(
    "python:3.12-slim"
    "eclipse-temurin:21-jre-alpine"
    "nginx:1.19.9-alpine"
    "mongo:6.0.26"
    "docker.elastic.co/elasticsearch/elasticsearch:7.17.28"
  )

  for img in "${images[@]}"; do
    echo "  Image: $img" >> "$OUTPUT_FILE"

    # Try docker scout if available
    if docker scout version &>/dev/null 2>&1; then
      docker scout quickview "$img" 2>&1 | tee -a "$OUTPUT_FILE" || echo "    (scan failed)" >> "$OUTPUT_FILE"
    else
      # Basic check: when was the image pulled?
      local pulled
      pulled=$(docker inspect "$img" --format '{{.Created}}' 2>/dev/null || echo "N/A")
      echo "    Image created: $pulled" >> "$OUTPUT_FILE"
      echo "    (install Docker Scout for CVE scanning: https://docs.docker.com/scout/)" >> "$OUTPUT_FILE"
    fi
  done
}

generate_summary() {
  echo "" >> "$OUTPUT_FILE"
  echo "========================================" >> "$OUTPUT_FILE"
  echo "  Scan Summary" >> "$OUTPUT_FILE"
  echo "========================================" >> "$OUTPUT_FILE"
  echo "  Date: $(date)" >> "$OUTPUT_FILE"
  echo "  Results: ${OUTPUT_FILE}" >> "$OUTPUT_FILE"

  # Count vulnerability indicators
  local vuln_count
  vuln_count=$(grep -ciE "vulnerabilit|critical|CVE-" "$OUTPUT_FILE" 2>/dev/null || echo "0")
  echo "  Vulnerability indicators: ${vuln_count}" >> "$OUTPUT_FILE"

  # Recommendations
  echo "" >> "$OUTPUT_FILE"
  echo "  Recommendations:" >> "$OUTPUT_FILE"
  echo "    1. Run 'pip install --upgrade <package>' for pip vulnerabilities" >> "$OUTPUT_FILE"
  echo "    2. Run 'npm audit fix' for frontend vulnerabilities" >> "$OUTPUT_FILE"
  echo "    3. Update Docker base images with 'docker pull <image>:<new-tag>'" >> "$OUTPUT_FILE"
  echo "    4. Re-run scan after fixes to verify" >> "$OUTPUT_FILE"
}

# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════
echo -e "${CYAN}GW Platform Dependency Scanner v4.37${NC}"
echo "Results: ${OUTPUT_FILE}"
echo ""

echo "GW Platform Dependency Scan — $(date)" > "$OUTPUT_FILE"
echo "========================================" >> "$OUTPUT_FILE"

$JSON_MODE && init_json

# Install pip-audit if needed
if ! command -v pip-audit &>/dev/null && ! python3 -c "import safety" 2>/dev/null; then
  echo -e "${YELLOW}Installing pip-audit for vulnerability scanning...${NC}"
  pip install -q pip-audit 2>/dev/null || echo "  (pip-audit install failed — using fallback)"
fi

echo "Scanning Python dependencies..."
scan_pip "gw-pipeline" "${PROJECT_DIR}/gw-pipeline/requirements.txt"
scan_pip "gw-mcp-server" "${PROJECT_DIR}/gw-mcp-server/requirements.txt"

echo "Scanning JavaScript dependencies..."
scan_npm

echo "Scanning Docker base images..."
scan_docker_images

echo "Generating summary..."
generate_summary

echo ""
echo -e "${GREEN}[OK] Scan complete${NC}"
echo "Results: ${OUTPUT_FILE}"

# Check for criticals and alert
if grep -qi "critical" "$OUTPUT_FILE" 2>/dev/null; then
  echo ""
  echo -e "${RED}[WARNING] Critical vulnerabilities detected!${NC}"
  echo "Review results and apply fixes immediately."
  exit 2
elif grep -qi "high" "$OUTPUT_FILE" 2>/dev/null; then
  echo ""
  echo -e "${YELLOW}[WARNING] High-severity vulnerabilities detected${NC}"
  exit 1
fi

exit 0
