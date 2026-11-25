"""Environment allowlist boundary shared by live block pipeline children."""
import os

CHILD_ENV_DENYLIST = frozenset({
    "DATABASE_URL", "POSTGRES_PASSWORD", "JWT_SECRET",
    "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "SMTP_USER", "SMTP_PASSWORD",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GOOGLE_CLIENT_SECRET", "AGENTLEDGER_API_KEY",
    "MANAGED_UPLOAD_POST_API_KEY", "MANAGED_GEMINI_API_KEY", "UPLOAD_POST_API_KEY",
    "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    "OPENPANEL_CLIENT_SECRET", "ELEVENLABS_API_KEY",
})


def child_env(base=None):
    """Copy configured LLM/media settings while dropping unrelated server secrets."""
    env = dict(os.environ if base is None else base)
    for name in CHILD_ENV_DENYLIST:
        env.pop(name, None)
    return env
