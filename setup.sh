#!/usr/bin/env bash
set -euo pipefail

CYAN='\033[0;36m'
ICE='\033[1;96m'
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
DIM='\033[2m'
RESET='\033[0m'

step() { printf "${CYAN}[%02d/08]${RESET} %s\n" "$1" "$2"; }
ok() { printf "${GREEN}  ✓${RESET} %s\n" "$1"; }
warn() { printf "${YELLOW}  ⚠${RESET} %s\n" "$1"; }
fail() { printf "${RED}  ✗ %s${RESET}\n" "$1"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
cd "$SCRIPT_DIR"

clear 2>/dev/null || true
printf "${ICE}"
cat <<'ART'
                 .  *  .
              ___/\___
          ___/  ICE   \___          I C E B E R G
~~~~~~~~~/_______________\~~~~~~~~  R E S E A R C H
         \               /
          \  NAVIGATOR  /     Navigate. Dive. Verify. Synthesize.
           \    ◉      /
            \_________/
ART
printf "${RESET}\n"

BACKEND_PID=""
FRONTEND_PID=""
CLEANED_UP=false

MODE=""
case "${1:-}" in
    web|--web) MODE="web" ;;
    terminal|--terminal) MODE="terminal" ;;
    --help|-h)
        printf "Usage: ./setup.sh [web | terminal]\n"
        printf "  web       Launch the browser interface\n"
        printf "  terminal  Start an interactive research session in this terminal\n"
        exit 0
        ;;
    "") ;;
    *) fail "Unknown option: $1 (use --help for available modes)" ;;
esac

if [ -z "$MODE" ]; then
    if [ -t 0 ]; then
        printf "${ICE}Choose your dive interface${RESET}\n"
        printf "  ${CYAN}1${RESET}) Web app\n"
        printf "  ${CYAN}2${RESET}) Terminal search\n"
        printf "${DIM}Selection [1]: ${RESET}"
        read -r selection
        case "${selection:-1}" in
            1|web|Web) MODE="web" ;;
            2|terminal|Terminal) MODE="terminal" ;;
            *) fail "Choose 1 for Web or 2 for Terminal" ;;
        esac
    else
        MODE="web"
    fi
fi

step 1 "Scanning the expedition environment"
command -v uv >/dev/null 2>&1 || fail "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/"
ok "$(uv --version)"
if [ "$MODE" = "web" ]; then
    command -v npm >/dev/null 2>&1 || fail "Node.js and npm are required for Web mode."
    ok "Node.js $(node --version)"
else
    ok "Terminal mode selected"
fi

step 2 "Synchronizing the Python habitat"
[ -f uv.lock ] || fail "uv.lock is missing; restore it before launching the application"
uv sync --frozen
uv run --no-sync python -c 'import fastapi, uvicorn, pydantic, langgraph, mcp, iceberg_search'
ok "Project environment is locked, synced, and verified"

step 3 "Loading mission credentials"
if [ ! -f .env ]; then
    cp .env.example .env
    warn "Created .env from .env.example"
    fail "Add your API keys to .env, then run ./setup.sh again"
fi
ok ".env is ready"

step 4 "Preparing research storage"
mkdir -p data/originals data/converted data/downloads data/rag data/search_cache logs
ok "Data directories are ready"

step 5 "Preparing the command deck"
if [ "$MODE" = "web" ]; then
    if [ ! -d web/node_modules ]; then
        (cd web && npm ci)
    fi
    ok "Frontend dependencies are ready"
else
    ok "Browser dependencies are not needed in Terminal mode"
fi

step 6 "Surveying optional MCP modules"
if command -v mcp-medium-reader >/dev/null 2>&1 \
    && mcp-medium-reader doctor 2>/dev/null | grep -q 'version: OK'; then
    ok "Medium Reader MCP is ready"
else
    warn "Medium Reader MCP is disabled; install ZMediumToMarkdown and run mcp-medium-reader init to enable it"
fi
if uv tool list | grep -q '^paper-search-mcp '; then
    ok "Paper Search MCP is cached by uv"
else
    warn "Paper Search MCP will be installed by uv on first use"
fi
if command -v npx >/dev/null 2>&1; then
    ok "PDF Reader MCP will be initialized with the backend"
else
    warn "npx is unavailable; PyMuPDF will handle standard PDF ingestion"
fi

step 7 "Running preflight checks"
uv run --no-sync python -m compileall -q iceberg_search
ok "Backend modules compile successfully"
ok "Unavailable optional MCP servers will degrade gracefully"

ensure_port_available() {
    local port="$1"
    local service="$2"
    if command -v lsof >/dev/null 2>&1 \
        && lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        fail "$service cannot start: port $port is already in use. Stop the existing process, then run ./setup.sh again."
    fi
}

stop_process_group() {
    local pid="$1"
    local label="$2"
    local launcher_pgid=""
    local shell_pgid=""
    local target="$pid"
    [ -z "$pid" ] && return

    # Background jobs normally get their own process group after `set -m`.
    # Resolve that group instead of assuming the launcher PID is always the PGID.
    # Never signal the setup.sh process group: doing so could interrupt cleanup
    # before Uvicorn/Next children have exited.
    launcher_pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d '[:space:]' || true)"
    shell_pgid="$(ps -o pgid= -p "$$" 2>/dev/null | tr -d '[:space:]' || true)"
    if [ -n "$launcher_pgid" ] && [ "$launcher_pgid" != "$shell_pgid" ]; then
        target="-$launcher_pgid"
    fi

    if kill -0 -- "$target" 2>/dev/null || kill -0 "$pid" 2>/dev/null; then
        kill -TERM -- "$target" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
        for _ in $(seq 1 20); do
            if ! kill -0 -- "$target" 2>/dev/null && ! kill -0 "$pid" 2>/dev/null; then
                break
            fi
            sleep 0.1
        done
        if kill -0 -- "$target" 2>/dev/null || kill -0 "$pid" 2>/dev/null; then
            warn "$label did not stop gracefully; forcing shutdown"
            kill -KILL -- "$target" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
        fi
        wait "$pid" 2>/dev/null || true
    fi
}

cleanup() {
    if [ "$CLEANED_UP" = true ]; then
        return
    fi
    CLEANED_UP=true
    printf "\n${DIM}Returning the expedition to base...${RESET}\n"
    stop_process_group "$FRONTEND_PID" "Frontend"
    stop_process_group "$BACKEND_PID" "Backend"
    FRONTEND_PID=""
    BACKEND_PID=""
    ok "All services stopped"
}

handle_signal() {
    # A second Ctrl+C during teardown must not abort cleanup and leave the
    # backend orphaned. Ignore signals until both service groups are stopped.
    trap '' INT TERM
    cleanup
    trap - EXIT INT TERM
    exit 130
}

trap cleanup EXIT
trap handle_signal INT TERM

step 8 "Launching the expedition"
# Give each service its own process group so Ctrl+C can stop npm/Next and
# uv/Uvicorn together with every child process they create.
set -m
ensure_port_available 8000 "Backend"
uv run --frozen python server.py &
BACKEND_PID=$!
for attempt in $(seq 1 45); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        fail "Backend exited during startup; inspect the log above"
    fi
    if curl -fsS http://localhost:8000/api/library >/dev/null 2>&1; then
        ok "Backend surfaced at http://localhost:8000"
        break
    fi
    [ "$attempt" -eq 45 ] && fail "Backend did not become healthy within 45 seconds"
    sleep 1
done

if [ "$MODE" = "terminal" ]; then
    printf "\n${ICE}  ◆ Terminal sonar online${RESET}\n"
    printf "  ${DIM}Press Ctrl+C at any time to cancel and surface.${RESET}\n\n"
    # Keep `set -e` from bypassing cleanup when the terminal client exits
    # with 130 after Ctrl+C.
    if uv run --frozen python terminal_gui.py; then
        EXIT_CODE=0
    else
        EXIT_CODE=$?
    fi
    cleanup
    trap - EXIT INT TERM
    exit "$EXIT_CODE"
fi

ensure_port_available 3000 "Frontend"
(cd web && exec npm run dev) &
FRONTEND_PID=$!
for attempt in $(seq 1 60); do
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
        fail "Frontend exited during startup; inspect the log above"
    fi
    if curl -fsS http://localhost:3000/ >/dev/null 2>&1; then
        ok "Command deck surfaced at http://localhost:3000"
        break
    fi
    [ "$attempt" -eq 60 ] && fail "Frontend did not become healthy within 60 seconds"
    sleep 1
done

printf "\n${ICE}  ◆ Expedition online${RESET}\n"
printf "  ${BLUE}UI${RESET}   http://localhost:3000\n"
printf "  ${BLUE}API${RESET}  http://localhost:8000\n"
printf "  ${DIM}Press Ctrl+C to surface and stop all services.${RESET}\n\n"

if command -v open >/dev/null 2>&1; then
    open http://localhost:3000 2>/dev/null || true
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://localhost:3000 2>/dev/null || true
fi

# Ctrl+C is commonly delivered to the foreground Next.js process first.
# `wait` then returns 130; handle that status explicitly so `set -e` cannot
# exit setup.sh before it terminates the separate backend process group.
if wait "$FRONTEND_PID"; then
    EXIT_CODE=0
else
    EXIT_CODE=$?
fi
cleanup
trap - EXIT INT TERM
exit "$EXIT_CODE"
