#!/usr/bin/env python3
"""
Módulo e utilitário CLI para envio de notificações ao Telegram.
Usado para avisos de conclusão de atualização e relato de falhas das bases.

Variáveis de ambiente (lidas de os.environ, .env local ou ~/.telegram_notifier.env):
  - TELEGRAM_BOT_TOKEN: Token do bot gerado pelo @BotFather
  - TELEGRAM_CHAT_ID:   ID do chat ou canal para onde enviar as notificações

Uso via CLI:
  python scripts/notify_telegram.py --projeto "CVM" --status "sucesso" --duracao "15 min" --detalhes "ipe_docs=178220"
  python scripts/notify_telegram.py --projeto "CVM" --status "falha" --duracao "5 min" --erros "ipe (exit 139)" --log-file "/caminho/log.log"
  python scripts/notify_telegram.py --test

Uso via Python:
  from scripts.notify_telegram import notify_telegram
  notify_telegram(projeto="CVM", status="sucesso", duracao="15 min", detalhes="...")
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


def load_env_file(filepath: Path) -> None:
    """Carrega variáveis de um arquivo .env simples sem sobrepor variáveis existentes."""
    if not filepath.is_file():
        return
    try:
        for line in filepath.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass


def get_credentials() -> tuple[str, str]:
    """Obtém TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID de os.environ, .env local ou ~/.telegram_notifier.env."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if token and chat_id:
        return token, chat_id

    # Tenta .env na raiz do projeto (subindo até 2 níveis)
    here = Path(__file__).resolve().parent
    for candidate in [here / ".env", here.parent / ".env", here.parent.parent / ".env"]:
        load_env_file(candidate)
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if token and chat_id:
            return token, chat_id

    # Tenta arquivo central de configuração global do usuário
    global_env = Path.home() / ".telegram_notifier.env"
    load_env_file(global_env)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return token, chat_id


def format_message(
    projeto: str,
    status: str,
    duracao: str | None = None,
    detalhes: str | None = None,
    erros: str | None = None,
    log_file: str | None = None,
) -> str:
    status_lower = status.lower()
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    if status_lower in ("sucesso", "ok", "success"):
        header = f"✅ <b>[{html.escape(projeto)}] Atualização Concluída</b>"
    elif status_lower in ("falha", "erro", "error", "failed"):
        header = f"🚨 <b>[{html.escape(projeto)}] Falha na Atualização</b>"
    elif status_lower in ("aviso", "alerta", "warning"):
        header = f"⚠️ <b>[{html.escape(projeto)}] Atualização com Alertas</b>"
    else:
        header = f"ℹ️ <b>[{html.escape(projeto)}] Notificação ({html.escape(status)})</b>"

    lines = [header, ""]

    if duracao:
        lines.append(f"⏱ <b>Duração:</b> {html.escape(str(duracao))}")
    if detalhes:
        lines.append(f"📊 <b>Detalhes:</b> {html.escape(str(detalhes))}")
    if erros:
        lines.append(f"❌ <b>Erros/Avisos:</b> <code>{html.escape(str(erros))}</code>")
    if log_file:
        lines.append(f"📄 <b>Log:</b> <code>{html.escape(str(log_file))}</code>")

    lines.append(f"📅 <b>Data:</b> {agora}")
    return "\n".join(lines)


def notify_telegram(
    projeto: str,
    status: str,
    duracao: str | None = None,
    detalhes: str | None = None,
    erros: str | None = None,
    log_file: str | None = None,
    timeout: int = 15,
) -> bool:
    """Envia notificação ao Telegram. Retorna True se enviado ou se silenciado (sem credenciais), False em erro de envio."""
    token, chat_id = get_credentials()

    if not token or not chat_id:
        print("[Telegram] Notificação ignorada: TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configurados.")
        return True

    text = format_message(
        projeto=projeto,
        status=status,
        duracao=duracao,
        detalhes=detalhes,
        erros=erros,
        log_file=log_file,
    )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                print(f"[Telegram] Mensagem enviada com sucesso para [{projeto}] ({status}).")
                return True
            else:
                print(f"[Telegram] Resposta inesperada do Telegram: HTTP {resp.status}")
                return False
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"[Telegram] Erro HTTP da API do Telegram ({e.code}): {err_body}")
        return False
    except Exception as e:
        print(f"[Telegram] Falha na conexão com Telegram: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Envia notificação ao Telegram.")
    parser.add_argument("--projeto", default="CVM", help="Nome do projeto / base (ex: CVM, CMF, CNBV, IMEA, ANAC)")
    parser.add_argument("--status", default="sucesso", help="Status: sucesso, falha, aviso")
    parser.add_argument("--duracao", default=None, help="Tempo de duração (ex: 15 min)")
    parser.add_argument("--detalhes", default=None, help="Métricas ou resumo da execução")
    parser.add_argument("--erros", default=None, help="Mensagem ou lista de erros")
    parser.add_argument("--log-file", default=None, help="Caminho do arquivo de log")
    parser.add_argument("--test", action="store_true", help="Dispara uma notificação de teste")

    args = parser.parse_args()

    if args.test:
        token, chat_id = get_credentials()
        if not token or not chat_id:
            print("[Telegram TESTE] ⚠️ TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não estão configurados.")
            print("Configure-os no .env do projeto ou em ~/.telegram_notifier.env")
            sys.exit(1)
        sucesso = notify_telegram(
            projeto=args.projeto,
            status="ok",
            duracao="0s",
            detalhes="Teste de comunicação com o bot do Telegram realizado com sucesso!",
        )
        sys.exit(0 if sucesso else 1)

    ok = notify_telegram(
        projeto=args.projeto,
        status=args.status,
        duracao=args.duracao,
        detalhes=args.detalhes,
        erros=args.erros,
        log_file=args.log_file,
    )
    # Sempre sai 0 para não travar pipelines chamadores
    sys.exit(0)


if __name__ == "__main__":
    main()
