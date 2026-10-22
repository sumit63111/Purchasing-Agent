import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / ".env")


# ==========================================
# LLM provider (openrouter or gemini)
# ==========================================
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openrouter").lower()

PROVIDERS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": os.getenv("OPENROUTER_API_KEY", ""),
        "model": os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-120b"),
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key": os.getenv("GEMINI_API_KEY", ""),
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    },
}
LLM = PROVIDERS.get(LLM_PROVIDER, PROVIDERS["openrouter"])

AGENT_MODE = os.getenv("AGENT_MODE", "auto")
MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", 30))
MAX_TOKENS = int(os.getenv("AGENT_MAX_TOKENS", 4000))
MAX_VERIFY_ATTEMPTS = 3


# ==========================================
# Data
# ==========================================
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "purchasing.db"))
SIMULATION_DATE = os.getenv("SIMULATION_DATE", "2026-10-22")


# ==========================================
# Purchasing policy
# ==========================================
AUTO_APPROVE_LIMIT = float(os.getenv("AUTO_APPROVE_LIMIT", 3000))
MAX_PRICE_PREMIUM = float(os.getenv("MAX_PRICE_PREMIUM", 0.10))
MAX_COVER_DAYS = int(os.getenv("MAX_COVER_DAYS", 30))
MIN_FILL_RATE = 0.85

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")


def pick_agent_mode(requested=None):
    mode = (requested or AGENT_MODE).lower()
    if mode == "auto":
        return "llm" if LLM["api_key"] else "rules"
    return mode
