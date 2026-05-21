#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Universal Utility Agent · Phase 1 + Phase 2 deployment
#
# Usage:
#   bash deploy.sh [OPTIONS]
#
# Options:
#   --env <dev|staging|prod>    Environment (default: dev)
#   --suffix <string>           Unique suffix (default: ua001)
#   --skip-infra                Skip Terraform, go straight to code deploy
#   --skip-orchestrator         Skip orchestrator func publish
#   --skip-registry             Skip registry func publish
#   --skip-ui                   Skip React build + SWA deploy
#   --skip-seed                 Skip Cosmos DB agent seeding
#   --skip-smoke-tests          Skip smoke tests after deployment
#   --destroy                   Terraform destroy (tear down everything)
#
# Prerequisites:
#   az         (Azure CLI, logged in)
#   terraform  (>= 1.7)
#   func       (Azure Functions Core Tools v4)
#   npm        (Node.js >= 18)
#   python3    (>= 3.11 with bcrypt: pip install bcrypt)
#   swa        (Static Web Apps CLI: npm i -g @azure/static-web-apps-cli)
#   jq
# =============================================================================

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
ENV="dev"
SUFFIX="ua001"
SKIP_INFRA=false
SKIP_ORCH=false
SKIP_REG=false
SKIP_UI=false
SKIP_SEED=false
SKIP_SMOKE=false
DESTROY=false

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../" && pwd)"
INFRA_DIR="$SCRIPT_DIR/infra"
ORCH_DIR="$SCRIPT_DIR/orchestrator"
REG_DIR="$SCRIPT_DIR/registry"
UI_DIR="$SCRIPT_DIR/registry-ui"

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --env)               ENV="$2";        shift 2 ;;
    --suffix)            SUFFIX="$2";     shift 2 ;;
    --skip-infra)        SKIP_INFRA=true; shift   ;;
    --skip-orchestrator) SKIP_ORCH=true;  shift   ;;
    --skip-registry)     SKIP_REG=true;   shift   ;;
    --skip-ui)           SKIP_UI=true;    shift   ;;
    --skip-smoke-tests)  SKIP_SMOKE=true; shift   ;;
    --destroy)           DESTROY=true;    shift   ;;
    *) echo "Unknown option: $1"; exit 1           ;;
  esac
done

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
log_h()    { echo -e "\n${BOLD}${CYAN}━━━  $1  ━━━${RESET}"; }
log_ok()   { echo -e "${GREEN}  ✓  $1${RESET}"; }
log_warn() { echo -e "${YELLOW}  !  $1${RESET}"; }
log_info() { echo -e "     $1"; }

# ── Banner ────────────────────────────────────────────────────────────────────
echo -e "${BOLD}"
echo -e "╔══════════════════════════════════════════════════════════╗"
echo -e "║    Universal Utility Agent — Full Deployment             ║"
echo -e "╚══════════════════════════════════════════════════════════╝${RESET}"
echo -e "  Environment : ${CYAN}${ENV}${RESET}  |  Suffix : ${CYAN}${SUFFIX}${RESET}"
echo -e "  Skip infra  : $SKIP_INFRA  |  Skip UI : $SKIP_UI"

# ── Prerequisite check ────────────────────────────────────────────────────────
log_h "Checking prerequisites"
for cmd in az terraform func npm python3 jq swa; do
  if command -v "$cmd" &>/dev/null; then
    log_ok "$cmd ($(command -v $cmd))"
  else
    echo -e "${RED}  ✗  $cmd not found${RESET}"
    [[ "$cmd" == "swa" ]] && echo "     Install with: npm i -g @azure/static-web-apps-cli"
    exit 1
  fi
done

if ! az account show &>/dev/null; then
  echo -e "${RED}  ✗  Not logged in to Azure. Run: az login${RESET}"
  exit 1
fi
log_ok "Azure: $(az account show --query name -o tsv)"

# Check and install bcrypt if needed
if ! python3 -c "import bcrypt" 2>/dev/null; then
  log_warn "bcrypt Python module not found. Installing..."
  python3 -m pip install bcrypt -q
  log_ok "bcrypt installed"
else
  log_ok "bcrypt (Python module)"
fi

# ── Destroy mode ──────────────────────────────────────────────────────────────
if [[ "$DESTROY" == "true" ]]; then
  log_h "Destroying all infrastructure"
  log_warn "This deletes EVERYTHING. Ctrl+C to cancel. Continuing in 10 s…"
  sleep 10
  cd "$INFRA_DIR"
  terraform destroy -var="environment=$ENV" -var="suffix=$SUFFIX" -auto-approve
  log_ok "All resources destroyed."
  exit 0
fi

# =============================================================================
# STEP 1 — Terraform
# =============================================================================
if [[ "$SKIP_INFRA" == "false" ]]; then
  log_h "Step 1 — Terraform: provision infrastructure"
  cd "$INFRA_DIR"

  [[ ! -f terraform.tfvars ]] && cp terraform.tfvars.example terraform.tfvars && \
    log_warn "Created terraform.tfvars from example — review and re-run, or continue."

  terraform init -upgrade -input=false
  terraform validate
  terraform plan -var="environment=$ENV" -var="suffix=$SUFFIX" -out=tfplan -input=false
  terraform apply tfplan
  rm -f tfplan
  log_ok "Infrastructure provisioned."
else
  log_h "Step 1 — Skipping Terraform (--skip-infra)"
  cd "$INFRA_DIR"
fi

# ── Capture Terraform outputs ─────────────────────────────────────────────────
log_h "Reading Terraform outputs"
RG_NAME=$(terraform output -raw resource_group_name)
KV_NAME=$(terraform output -raw key_vault_name)
KV_URL=$(terraform output -raw key_vault_uri)
COSMOS_ACCOUNT=$(terraform output -raw cosmos_account_name)
COSMOS_DB=$(terraform output -raw cosmos_database_name)
ORCH_APP=$(terraform output -raw orchestrator_app_name)
ORCH_URL=$(terraform output -raw orchestrator_url)
REG_APP=$(terraform output -raw registry_app_name)
REG_URL=$(terraform output -raw registry_url)
SWA_URL=$(terraform output -raw swa_url)

log_ok "Resource group  : $RG_NAME"
log_ok "Orchestrator    : $ORCH_APP"
log_ok "Registry API    : $REG_APP"
log_ok "Registry UI SWA : $SWA_URL"

# Persist to .env.deploy
ENV_FILE="$SCRIPT_DIR/.env.deploy"
cat > "$ENV_FILE" << ENVEOF
# Auto-generated by deploy.sh — $(date -u +"%Y-%m-%dT%H:%M:%SZ")
export RG_NAME="$RG_NAME"
export KV_NAME="$KV_NAME"
export KV_URL="$KV_URL"
export COSMOS_ACCOUNT="$COSMOS_ACCOUNT"
export COSMOS_DB="$COSMOS_DB"
export FUNC_APP_NAME="$ORCH_APP"
export FUNC_URL="$ORCH_URL"
export REGISTRY_APP_NAME="$REG_APP"
export REGISTRY_URL="$REG_URL"
export SWA_URL="$SWA_URL"
ENVEOF

# =============================================================================
# STEP 2 — Set admin credentials (interactive, only if not already set)
# =============================================================================
log_h "Step 2 — Admin credentials for Registry UI"

EXISTING=$(az keyvault secret show --vault-name "$KV_NAME" --name "admin-password" \
  --query value -o tsv 2>/dev/null || true)

if [[ -z "$EXISTING" ]]; then
  log_warn "Agent Registry admin credentials are still not set. Setting real credentials now."
  echo ""
  read -rp "  Enter admin username [admin]: " ADMIN_USER
  ADMIN_USER="${ADMIN_USER:-admin}"

  read -rsp "  Enter admin password: " ADMIN_PASS; echo
  if [[ -z "$ADMIN_PASS" ]]; then
    log_warn "Password cannot be empty — skipping. Set manually with:"
    log_warn "  az keyvault secret set --vault-name $KV_NAME --name admin-password --value '<bcrypt_hash>'"
  else
    BCRYPT_HASH=$(python3 -c "import bcrypt; print(bcrypt.hashpw(b'$ADMIN_PASS', bcrypt.gensalt()).decode())")
    az keyvault secret set --vault-name "$KV_NAME" --name "admin-username" \
      --value "$ADMIN_USER" --output none
    az keyvault secret set --vault-name "$KV_NAME" --name "admin-password" \
      --value "$BCRYPT_HASH" --output none
    log_ok "Admin credentials stored in Key Vault."
  fi
else
  log_ok "admin-password already set — skipping."
fi

# =============================================================================
# STEP 3 — Deploy Orchestrator Function App
# =============================================================================
if [[ "$SKIP_ORCH" == "false" ]]; then
  log_h "Step 3 — Deploy orchestrator function app"

  if [[ ! -d "$ORCH_DIR" ]]; then
    log_warn "Orchestrator source not found at $ORCH_DIR — skipping."
  else
    cd "$ORCH_DIR"
    func azure functionapp publish "$ORCH_APP" --python --build remote
    log_ok "Orchestrator deployed."

    # Store host key in Key Vault
    sleep 20
    ORCH_KEY=$(az functionapp keys list --name "$ORCH_APP" --resource-group "$RG_NAME" \
      --query "functionKeys.default" -o tsv)
    az keyvault secret set --vault-name "$KV_NAME" \
      --name "orchestrator-host-key" --value "$ORCH_KEY" --output none
    echo "export FUNC_KEY=\"$ORCH_KEY\"" >> "$ENV_FILE"
    log_ok "Orchestrator host key stored in Key Vault."
  fi
else
  log_h "Step 3 — Skipping orchestrator deploy (--skip-orchestrator)"
fi

# =============================================================================
# STEP 4 — Deploy Registry Function App
# =============================================================================
if [[ "$SKIP_REG" == "false" ]]; then
  log_h "Step 4 — Deploy registry function app"

  if [[ ! -d "$REG_DIR" ]]; then
    log_warn "Agent Registry source not found at $REG_DIR — skipping."
  else
    cd "$REG_DIR"
    func azure functionapp publish "$REG_APP" --python --build remote
    log_ok "Agent Registry API deployed."

    # Store registry host key in Key Vault
    sleep 20
    REG_KEY=$(az functionapp keys list --name "$REG_APP" --resource-group "$RG_NAME" \
      --query "functionKeys.default" -o tsv)
    az keyvault secret set --vault-name "$KV_NAME" \
      --name "registry-host-key" --value "$REG_KEY" --output none
    echo "export REGISTRY_KEY=\"$REG_KEY\"" >> "$ENV_FILE"
    log_ok "Registry host key stored in Key Vault."
  fi
else
  log_h "Step 4 — Skipping registry deploy (--skip-registry)"
fi

# =============================================================================
# STEP 5 — Build and deploy React UI to Static Web App
# =============================================================================
if [[ "$SKIP_UI" == "false" ]]; then
  log_h "Step 5 — Build and deploy Registry UI"

  if [[ ! -d "$UI_DIR" ]]; then
    log_warn "UI source not found at $UI_DIR — skipping."
  else
    # Retrieve registry key for the build
    REG_KEY_BUILD=$(az keyvault secret show --vault-name "$KV_NAME" \
      --name "registry-host-key" --query value -o tsv 2>/dev/null || echo "")

    # Write .env.production for the Vite build
    cat > "$UI_DIR/.env.production" << UIENV
VITE_REGISTRY_URL=$REG_URL
VITE_FUNC_CODE=$REG_KEY_BUILD
UIENV
    log_ok ".env.production written for Vite build."

    cd "$UI_DIR"
    npm install --silent
    npm run build
    log_ok "React app built → dist/"

    # Deploy to SWA using token from Key Vault
    SWA_TOKEN=$(az keyvault secret show --vault-name "$KV_NAME" \
      --name "swa-deployment-token" --query value -o tsv)

    swa deploy ./dist \
      --deployment-token "$SWA_TOKEN" \
      --env production
    log_ok "Registry UI deployed to $SWA_URL"
  fi
else
  log_h "Step 5 — Skipping UI deploy (--skip-ui)"
fi

# =============================================================================
# STEP 6 — Smoke tests
# =============================================================================
if [[ "$SKIP_SMOKE" == "false" ]]; then
  log_h "Step 6 — Smoke tests"
  sleep 30   # allow function apps to warm up

  ORCH_KEY_LIVE=$(az keyvault secret show --vault-name "$KV_NAME" \
    --name "orchestrator-host-key" --query value -o tsv 2>/dev/null || echo "")
  REG_KEY_LIVE=$(az keyvault secret show --vault-name "$KV_NAME" \
    --name "registry-host-key" --query value -o tsv 2>/dev/null || echo "")

  # Orchestrator health
  ORCH_HEALTH=$(curl -sf "${ORCH_URL}/api/health" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo "unreachable")
  [[ "$ORCH_HEALTH" == "ok" ]] && log_ok "Orchestrator health: ok" || log_warn "Orchestrator health: $ORCH_HEALTH"

  # Registry health
  REG_HEALTH=$(curl -sf "${REG_URL}/api/health" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo "unreachable")
  [[ "$REG_HEALTH" == "ok" ]] && log_ok "Registry health: ok" || log_warn "Registry health: $REG_HEALTH"

  # Registry auth
  if [[ -n "$REG_KEY_LIVE" ]]; then
    AUTH_STATUS=$(curl -sf "${REG_URL}/api/auth/verify?code=${REG_KEY_LIVE}" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('valid','?'))" 2>/dev/null || echo "unreachable")
    log_ok "Registry auth verify: valid=$AUTH_STATUS"
  fi
else
  log_h "Step 6 — Skipping smoke tests (--skip-smoke-tests)"
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════════╗"
echo "║                Deployment complete!                      ║"
echo -e "╚══════════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  Orchestrator chat  : ${CYAN}${ORCH_URL}/api/chat${RESET}"
echo -e "  Registry API       : ${CYAN}${REG_URL}/api/agents${RESET}"
echo -e "  Registry UI        : ${CYAN}${SWA_URL}${RESET}"
echo -e "  Registry dashboard : ${CYAN}${REG_URL}/api/agents/dashboard${RESET}"
echo ""
echo -e "  Restore env vars:  ${YELLOW}source .env.deploy${RESET}"
echo ""
echo -e "  Test chat:"
echo -e "  ${YELLOW}curl -X POST \"${ORCH_URL}/api/chat?code=\${FUNC_KEY}\" \\${RESET}"
echo -e "  ${YELLOW}  -H 'Content-Type: application/json' \\${RESET}"
echo -e "  ${YELLOW}  -d '{\"message\":\"Why is my bill high?\",\"customer_id\":\"CUST-1001\"}' | jq .${RESET}"
echo ""
echo -e "  Next step — change admin password (if you skipped the prompt):"
echo -e "  ${YELLOW}HASH=\$(python3 -c \"import bcrypt; print(bcrypt.hashpw(b'yourpass', bcrypt.gensalt()).decode())\")${RESET}"
echo -e "  ${YELLOW}az keyvault secret set --vault-name $KV_NAME --name admin-password --value \"\$HASH\"${RESET}"
echo ""
