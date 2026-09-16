import argparse
import os

import requests


def _print_failure(label, exc):
    print(f"{label}=FAIL:{exc.__class__.__name__}")


def _check_gemini(api_key, model):
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents="Reply exactly OK")
        text = str(getattr(response, "text", "")).strip()
        if text != "OK":
            raise ValueError("unexpected response")
        print("GEMINI=OK")
        return True
    except Exception as exc:
        _print_failure("GEMINI", exc)
        return False


def _check_telegram(token, chat_id, timeout, send_test_message=False):
    base = f"https://api.telegram.org/bot{token}"
    try:
        response = requests.get(base + "/getMe", timeout=timeout)
        response.raise_for_status()
        if not response.json().get("ok"):
            raise ValueError("getMe")
        print("TELEGRAM_AUTH=OK")

        response = requests.get(base + "/getChat", params={"chat_id": chat_id}, timeout=timeout)
        response.raise_for_status()
        if not response.json().get("ok"):
            raise ValueError("getChat")
        print("TELEGRAM_CHAT=OK")

        if send_test_message:
            response = requests.post(
                base + "/sendMessage",
                json={"chat_id": chat_id, "text": "✅ V6 SYSTEM TEST OK — fresh verification"},
                timeout=timeout,
            )
            response.raise_for_status()
            if not response.json().get("ok"):
                raise ValueError("sendMessage")
            print("TELEGRAM_SEND=OK")
        else:
            print("TELEGRAM_SEND=SKIPPED")
        return True
    except Exception as exc:
        _print_failure("TELEGRAM", exc)
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Safe Gemini + Telegram connectivity check")
    parser.add_argument(
        "--send-test-message",
        action="store_true",
        help="Send one Telegram smoke-test message after auth/chat checks pass",
    )
    args = parser.parse_args(argv)

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    try:
        timeout = float(os.getenv("HTTP_TIMEOUT_SECONDS", "8"))
    except ValueError:
        timeout = 8.0

    missing = False
    if not gemini_key:
        print("GEMINI=MISSING")
        missing = True
    if not telegram_token or not telegram_chat_id:
        print("TELEGRAM=MISSING")
        missing = True
    if missing:
        print("HEALTHCHECK=FAIL")
        return 1

    gemini_ok = _check_gemini(gemini_key, model)
    telegram_ok = _check_telegram(
        telegram_token,
        telegram_chat_id,
        timeout,
        send_test_message=args.send_test_message,
    )
    ok = gemini_ok and telegram_ok
    print("HEALTHCHECK=OK" if ok else "HEALTHCHECK=FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
