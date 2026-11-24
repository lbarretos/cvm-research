import os
import unittest
from unittest.mock import patch, MagicMock
import urllib.error
from scripts.notify_telegram import format_message, notify_telegram, get_credentials


class TestNotifyTelegram(unittest.TestCase):
    def test_format_message_success(self):
        msg = format_message(projeto="CVM", status="sucesso", duracao="10 min", detalhes="156 empresas")
        self.assertIn("✅ <b>[CVM] Atualização Concluída</b>", msg)
        self.assertIn("⏱ <b>Duração:</b> 10 min", msg)
        self.assertIn("📊 <b>Detalhes:</b> 156 empresas", msg)

    def test_format_message_failure(self):
        msg = format_message(projeto="CVM", status="falha", duracao="2 min", erros="ipe (exit 1)", log_file="/tmp/log.log")
        self.assertIn("🚨 <b>[CVM] Falha na Atualização</b>", msg)
        self.assertIn("❌ <b>Erros/Avisos:</b> <code>ipe (exit 1)</code>", msg)
        self.assertIn("📄 <b>Log:</b> <code>/tmp/log.log</code>", msg)

    def test_format_message_html_escape(self):
        msg = format_message(projeto="CVM & B3", status="alerta", erros="<script>alert(1)</script>")
        self.assertIn("CVM &amp; B3", msg)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", msg)

    def test_notify_telegram_unconfigured(self):
        old_token = os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        old_chat = os.environ.pop("TELEGRAM_CHAT_ID", None)
        try:
            # Deve retornar True (silencioso) e não lançar exceção
            self.assertTrue(notify_telegram(projeto="CVM", status="sucesso"))
        finally:
            if old_token: os.environ["TELEGRAM_BOT_TOKEN"] = old_token
            if old_chat: os.environ["TELEGRAM_CHAT_ID"] = old_chat

    def test_notify_telegram_success(self):
        old_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        old_chat = os.environ.get("TELEGRAM_CHAT_ID")
        os.environ["TELEGRAM_BOT_TOKEN"] = "fake_token_123"
        os.environ["TELEGRAM_CHAT_ID"] = "12345678"

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp

        try:
            with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
                res = notify_telegram(projeto="CVM", status="sucesso", duracao="5 min")
                self.assertTrue(res)
                mock_urlopen.assert_called_once()
                req = mock_urlopen.call_args[0][0]
                self.assertIn("fake_token_123", req.full_url)
                self.assertIn(b"12345678", req.data)
        finally:
            if old_token is not None:
                os.environ["TELEGRAM_BOT_TOKEN"] = old_token
            else:
                os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            if old_chat is not None:
                os.environ["TELEGRAM_CHAT_ID"] = old_chat
            else:
                os.environ.pop("TELEGRAM_CHAT_ID", None)

    def test_notify_telegram_http_error(self):
        old_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        old_chat = os.environ.get("TELEGRAM_CHAT_ID")
        os.environ["TELEGRAM_BOT_TOKEN"] = "fake_token_123"
        os.environ["TELEGRAM_CHAT_ID"] = "12345678"

        err = urllib.error.HTTPError("url", 401, "Unauthorized", {}, MagicMock(read=lambda: b"Unauthorized"))
        try:
            with patch("urllib.request.urlopen", side_effect=err):
                # Não deve explodir exceção, deve apenas retornar False
                self.assertFalse(notify_telegram(projeto="CVM", status="sucesso"))
        finally:
            if old_token is not None:
                os.environ["TELEGRAM_BOT_TOKEN"] = old_token
            else:
                os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            if old_chat is not None:
                os.environ["TELEGRAM_CHAT_ID"] = old_chat
            else:
                os.environ.pop("TELEGRAM_CHAT_ID", None)


if __name__ == "__main__":
    unittest.main()
