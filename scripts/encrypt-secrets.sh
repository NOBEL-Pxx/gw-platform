#!/bin/bash
#==============================================================================
# Secrets Encryption Helper — GravitationalWave Platform v4.37
# Encrypts sensitive values in .env files using openssl AES-256-CBC.
#
# Usage:
#   bash scripts/encrypt-secrets.sh encrypt < .env > .env.enc
#   bash scripts/encrypt-secrets.sh decrypt < .env.enc
#   bash scripts/encrypt-secrets.sh generate-key
#==============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
KEY_FILE="${HOME}/.gw-secrets-key"

# ── Key Management ─────────────────────────────────────────────────────────

generate_key() {
  if [ -f "$KEY_FILE" ]; then
    echo -e "${YELLOW}Key already exists: $KEY_FILE${NC}"
    echo "Overwrite? [y/N]: "
    read -r confirm
    [ "$confirm" != "y" ] && [ "$confirm" != "Y" ] && { echo "Aborted."; exit 0; }
  fi
  openssl rand -base64 32 > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
  echo -e "${GREEN}Encryption key generated: $KEY_FILE${NC}"
  echo "Store this key securely — you cannot decrypt without it."
}

# ── Encrypt / Decrypt ──────────────────────────────────────────────────────

encrypt_value() {
  local plaintext="$1"
  if [ ! -f "$KEY_FILE" ]; then
    echo -e "${RED}Error: Key not found. Run: $0 generate-key${NC}" >&2
    exit 1
  fi
  echo "$plaintext" | openssl enc -aes-256-cbc -salt -pbkdf2 -pass file:"$KEY_FILE" -base64
}

decrypt_value() {
  local ciphertext="$1"
  if [ ! -f "$KEY_FILE" ]; then
    echo -e "${RED}Error: Key not found. Run: $0 generate-key${NC}" >&2
    exit 1
  fi
  echo "$ciphertext" | openssl enc -aes-256-cbc -d -salt -pbkdf2 -pass file:"$KEY_FILE" -base64 2>/dev/null || {
    echo -e "${RED}Decryption failed — wrong key or corrupted data${NC}" >&2
    exit 1
  }
}

encrypt_env_file() {
  # Read .env, encrypt values, output encrypted version
  while IFS='=' read -r key value; do
    key=$(echo "$key" | xargs)
    [ -z "$key" ] && continue
    [ "${key:0:1}" = "#" ] && { echo "$key=$value"; continue; }

    # Only encrypt known sensitive keys
    case "$key" in
      DEEPSEEK_API_KEY|MONGO_ROOT_PASSWORD|MONGO_APP_PASSWORD|ES_PASSWORD|JWT_SECRET|GW_MASTER_KEY)
        local encrypted
        encrypted=$(encrypt_value "$value" 2>/dev/null)
        echo "${key}=ENC:${encrypted}"
        ;;
      *)
        echo "${key}=${value}"
        ;;
    esac
  done
}

decrypt_env_file() {
  while IFS='=' read -r key value; do
    key=$(echo "$key" | xargs)
    [ -z "$key" ] && continue
    [ "${key:0:1}" = "#" ] && { echo "$key=$value"; continue; }

    if echo "$value" | grep -q "^ENC:"; then
      local ciphertext="${value#ENC:}"
      local plaintext
      plaintext=$(decrypt_value "$ciphertext" 2>/dev/null || echo "DECRYPT_FAILED")
      echo "${key}=${plaintext}"
    else
      echo "${key}=${value}"
    fi
  done
}

# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════
case "${1:-}" in
  generate-key|genkey)
    generate_key
    ;;
  encrypt|enc)
    encrypt_env_file
    ;;
  decrypt|dec)
    decrypt_env_file
    ;;
  *)
    echo "GW Secrets Encryption v4.37"
    echo ""
    echo "Commands:"
    echo "  generate-key          Generate AES-256 encryption key"
    echo "  encrypt < .env        Encrypt sensitive values (to stdout)"
    echo "  decrypt < .env.enc    Decrypt encrypted values (to stdout)"
    echo ""
    echo "Example:"
    echo "  $0 generate-key"
    echo "  $0 encrypt < .env > .env.encrypted"
    echo "  $0 decrypt < .env.encrypted"
    ;;
esac
