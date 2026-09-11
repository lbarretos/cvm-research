#!/bin/bash
# Instala (ou remove) o agendamento semanal da base CVM Research no launchd do macOS.
# O job roda scripts/update_weekly.sh toda segunda-feira às 09:00 (a CVM publica
# os ZIPs entre 8h00 e 8h30). Se o Mac estiver dormindo, o launchd executa ao acordar.
#
# Uso:
#   bash scripts/install_weekly_launchd.sh              # instala/atualiza
#   bash scripts/install_weekly_launchd.sh --run-now    # instala e dispara uma execução imediata
#   bash scripts/install_weekly_launchd.sh --status     # mostra estado do job
#   bash scripts/install_weekly_launchd.sh --uninstall  # remove o agendamento
#
# Permissão macOS: se o log mostrar "Operation not permitted" ao acessar a pasta do
# projeto, adicione /bin/bash em Ajustes do Sistema → Privacidade e Segurança →
# Acesso Total ao Disco (a pasta Documentos é protegida pelo TCC).

set -eu

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.cvm-research.weekly-update"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
WEEKDAY="${WEEKDAY:-1}"   # 0=domingo, 1=segunda ... 6=sábado
HOUR="${HOUR:-9}"
MINUTE="${MINUTE:-0}"

case "${1:-}" in
  --uninstall)
    launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Agendamento removido ($LABEL)."
    exit 0
    ;;
  --status)
    launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "state =|program =|last exit code|run interval|runs =" || echo "Job não carregado."
    ls -1t "$PROJECT_DIR/logs"/update_*.log 2>/dev/null | head -1 | xargs -I{} sh -c 'echo "Último log: {}"; tail -3 "{}"'
    exit 0
    ;;
esac

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/logs"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$PROJECT_DIR/scripts/update_weekly.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key>
    <string>$HOME</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>$WEEKDAY</integer>
    <key>Hour</key>
    <integer>$HOUR</integer>
    <key>Minute</key>
    <integer>$MINUTE</integer>
  </dict>
  <key>RunAtLoad</key>
  <false/>
  <key>StandardOutPath</key>
  <string>$PROJECT_DIR/logs/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_DIR/logs/launchd.err.log</string>
</dict>
</plist>
PLIST

plutil -lint "$PLIST" >/dev/null
launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Agendamento instalado: $LABEL — weekday=$WEEKDAY ${HOUR}:$(printf '%02d' "$MINUTE")"
echo "Plist: $PLIST"

if [ "${1:-}" = "--run-now" ]; then
  launchctl kickstart -k "$DOMAIN/$LABEL"
  echo "Execução imediata disparada. Acompanhe em: $PROJECT_DIR/logs/"
fi
