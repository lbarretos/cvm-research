#!/bin/bash
# Inicia o CVM MCP Server em background
# Uso: bash scripts/mcp/start_mcp.sh [--port 8765]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
PIDFILE="/tmp/cvm_mcp.pid"
LOGFILE="$PROJECT_DIR/logs/cvm_mcp.log"
PORT="${2:-8765}"

mkdir -p "$PROJECT_DIR/logs"

# Matar instância anterior se existir
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Parando instância anterior (PID $OLD_PID)..."
        kill "$OLD_PID"
        sleep 1
    fi
    rm -f "$PIDFILE"
fi

echo "Iniciando CVM MCP Server na porta $PORT..."
nohup "$PYTHON" "$SCRIPT_DIR/cvm_mcp.py" --port "$PORT" \
    >> "$LOGFILE" 2>&1 &

echo $! > "$PIDFILE"
sleep 2

# Verificar se subiu
if curl -s "http://localhost:$PORT/mcp" > /dev/null 2>&1 || \
   kill -0 "$(cat $PIDFILE)" 2>/dev/null; then
    echo "✓ Servidor rodando (PID $(cat $PIDFILE)) — http://localhost:$PORT/mcp"
    echo "  Log: $LOGFILE"
else
    echo "✗ Falha ao iniciar. Veja o log: $LOGFILE"
    tail -20 "$LOGFILE"
fi
