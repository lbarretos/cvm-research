#!/bin/bash
# Instala (ou remove) o agendamento semanal da base CVM Research no launchd do macOS.
# O job chama scripts/update_weekly.sh --se-vencido em três gatilhos: toda segunda-feira
# às 09:00 (a CVM publica os ZIPs entre 8h00 e 8h30), no login (RunAtLoad) e a cada 4 h
# (StartInterval). O launchd só recupera um horário perdido com o Mac dormindo, não
# desligado; com os dois gatilhos extras, uma segunda perdida roda no mesmo dia. O
# --se-vencido faz os disparos extras saírem em segundos quando a semana já foi carregada.
#
# Uso:
#   bash scripts/install_weekly_launchd.sh              # instala/atualiza
#   bash scripts/install_weekly_launchd.sh --run-now    # instala e força uma execução imediata
#   bash scripts/install_weekly_launchd.sh --status     # estado do job, último sucesso e último log
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
INTERVALO_SEG="${INTERVALO_SEG:-14400}"   # re-checagem a cada 4 h
STAMP_FILE="$PROJECT_DIR/logs/.ultimo_sucesso"

case "${1:-}" in
  --uninstall)
    launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Agendamento removido ($LABEL)."
    exit 0
    ;;
  --status)
    launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "state =|program =|last exit code|run interval|runs =" || echo "Job não carregado."
    if [ -s "$STAMP_FILE" ]; then
      echo "Último sucesso: $(head -1 "$STAMP_FILE" | cut -d' ' -f2-)"
    else
      echo "Último sucesso: nenhum registrado ($STAMP_FILE)"
    fi
    echo "Situação: $(CVM_DIA_SEMANA="$WEEKDAY" CVM_HORA="$HOUR" bash "$PROJECT_DIR/scripts/update_weekly.sh" --verificar)"
    ls -1t "$PROJECT_DIR/logs"/update_*.log 2>/dev/null | head -1 | xargs -I{} sh -c 'echo "Último log: {}"; tail -3 "{}"'
    exit 0
    ;;
esac

# O plist grava o caminho absoluto deste checkout: instalado de uma cópia sem .venv/banco
# (ex.: um git worktree), o job trocaria o agendamento bom por um que falha toda vez.
if [ ! -x "$PROJECT_DIR/.venv/bin/python" ] || [ ! -f "$PROJECT_DIR/cvm_research.db" ]; then
  echo "ERRO: $PROJECT_DIR não tem .venv/bin/python e cvm_research.db — rode o instalador" >&2
  echo "      a partir do checkout principal do projeto. Agendamento atual mantido." >&2
  exit 1
fi

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
    <string>--se-vencido</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key>
    <string>$HOME</string>
    <key>CVM_DIA_SEMANA</key>
    <string>$WEEKDAY</string>
    <key>CVM_HORA</key>
    <string>$HOUR</string>
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
  <key>StartInterval</key>
  <integer>$INTERVALO_SEG</integer>
  <key>RunAtLoad</key>
  <true/>
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
echo "Agendamento instalado: $LABEL — weekday=$WEEKDAY ${HOUR}:$(printf '%02d' "$MINUTE"), no login e a cada $((INTERVALO_SEG / 3600)) h se a semana estiver pendente"
echo "Plist: $PLIST"
echo "Situação: $(CVM_DIA_SEMANA="$WEEKDAY" CVM_HORA="$HOUR" bash "$PROJECT_DIR/scripts/update_weekly.sh" --verificar)"

if [ "${1:-}" = "--run-now" ]; then
  # Direto, sem --se-vencido: força a carga mesmo com a semana em dia. Se o RunAtLoad
  # acabou de disparar uma execução, esta sai pelo lock.
  nohup bash "$PROJECT_DIR/scripts/update_weekly.sh" >>"$PROJECT_DIR/logs/launchd.out.log" 2>&1 &
  echo "Execução imediata disparada (pid $!). Acompanhe em: $PROJECT_DIR/logs/"
fi
