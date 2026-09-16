import io
import os
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import external_healthcheck


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise external_healthcheck.requests.HTTPError("request failed")

    def json(self):
        return self._payload


class ExternalHealthcheckTests(unittest.TestCase):
    def test_missing_credentials_fails_closed_without_network(self):
        buf = io.StringIO()
        env = {
            "GEMINI_API_KEY": "",
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
        }
        with patch.dict(os.environ, env, clear=True), redirect_stdout(buf):
            code = external_healthcheck.main([])
        self.assertEqual(code, 1)
        self.assertIn("GEMINI=MISSING", buf.getvalue())
        self.assertIn("TELEGRAM=MISSING", buf.getvalue())
        self.assertIn("HEALTHCHECK=FAIL", buf.getvalue())

    def test_default_model_is_gemini_3_6_flash(self):
        buf = io.StringIO()
        fake_client = Mock()
        fake_client.models.generate_content.return_value = types.SimpleNamespace(text="OK")
        fake_genai = types.SimpleNamespace(Client=Mock(return_value=fake_client))
        fake_google = types.SimpleNamespace(genai=fake_genai)
        env = {
            "GEMINI_API_KEY": "gem-secret",
            "TELEGRAM_BOT_TOKEN": "tg-secret",
            "TELEGRAM_CHAT_ID": "12345",
        }
        get_side_effect = [
            FakeResponse({"ok": True, "result": {"id": 1}}),
            FakeResponse({"ok": True, "result": {"id": 12345}}),
        ]
        with (
            patch.dict(os.environ, env, clear=True),
            patch.dict(sys.modules, {"google": fake_google}),
            patch.object(external_healthcheck.requests, "get", side_effect=get_side_effect),
            redirect_stdout(buf),
        ):
            code = external_healthcheck.main([])

        self.assertEqual(code, 0)
        self.assertEqual(
            fake_client.models.generate_content.call_args.kwargs["model"],
            "gemini-3.6-flash",
        )

    def test_scanner_default_model_is_gemini_3_6_flash(self):
        scanner_part = Path(__file__).resolve().parents[1] / "auto_scanner_v6.part00"
        source = scanner_part.read_text(encoding="utf-8")
        self.assertIn(
            'GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()',
            source,
        )
        self.assertNotIn("gemini-2.5-flash", source)

    def test_success_checks_gemini_bot_and_chat_without_sending(self):
        buf = io.StringIO()
        fake_client = Mock()
        fake_client.models.generate_content.return_value = types.SimpleNamespace(text="OK")
        fake_genai = types.SimpleNamespace(Client=Mock(return_value=fake_client))
        fake_google = types.SimpleNamespace(genai=fake_genai)
        env = {
            "GEMINI_API_KEY": "gem-secret",
            "GEMINI_MODEL": "gemini-test",
            "TELEGRAM_BOT_TOKEN": "tg-secret",
            "TELEGRAM_CHAT_ID": "12345",
            "HTTP_TIMEOUT_SECONDS": "3",
        }
        get_side_effect = [
            FakeResponse({"ok": True, "result": {"id": 1}}),
            FakeResponse({"ok": True, "result": {"id": 12345}}),
        ]
        with (
            patch.dict(os.environ, env, clear=True),
            patch.dict(sys.modules, {"google": fake_google}),
            patch.object(external_healthcheck.requests, "get", side_effect=get_side_effect) as get_mock,
            patch.object(external_healthcheck.requests, "post") as post_mock,
            redirect_stdout(buf),
        ):
            code = external_healthcheck.main([])

        self.assertEqual(code, 0)
        self.assertIn("GEMINI=OK", buf.getvalue())
        self.assertIn("TELEGRAM_AUTH=OK", buf.getvalue())
        self.assertIn("TELEGRAM_CHAT=OK", buf.getvalue())
        self.assertIn("TELEGRAM_SEND=SKIPPED", buf.getvalue())
        self.assertIn("HEALTHCHECK=OK", buf.getvalue())
        self.assertEqual(get_mock.call_count, 2)
        post_mock.assert_not_called()

    def test_send_flag_sends_one_telegram_message(self):
        buf = io.StringIO()
        fake_client = Mock()
        fake_client.models.generate_content.return_value = types.SimpleNamespace(text="OK")
        fake_genai = types.SimpleNamespace(Client=Mock(return_value=fake_client))
        fake_google = types.SimpleNamespace(genai=fake_genai)
        env = {
            "GEMINI_API_KEY": "gem-secret",
            "TELEGRAM_BOT_TOKEN": "tg-secret",
            "TELEGRAM_CHAT_ID": "12345",
        }
        get_side_effect = [
            FakeResponse({"ok": True, "result": {"id": 1}}),
            FakeResponse({"ok": True, "result": {"id": 12345}}),
        ]
        with (
            patch.dict(os.environ, env, clear=True),
            patch.dict(sys.modules, {"google": fake_google}),
            patch.object(external_healthcheck.requests, "get", side_effect=get_side_effect),
            patch.object(
                external_healthcheck.requests,
                "post",
                return_value=FakeResponse({"ok": True, "result": {"message_id": 7}}),
            ) as post_mock,
            redirect_stdout(buf),
        ):
            code = external_healthcheck.main(["--send-test-message"])

        self.assertEqual(code, 0)
        self.assertIn("TELEGRAM_SEND=OK", buf.getvalue())
        self.assertIn("HEALTHCHECK=OK", buf.getvalue())
        post_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
