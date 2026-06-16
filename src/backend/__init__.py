"""Backend package for the Purpose Creator API."""

# Optional: load a local .env for developer convenience (production should inject env vars).
# Resolve the .env path relative to the repo root so it works regardless of the cwd.
try:
    from pathlib import Path
    from dotenv import load_dotenv  # type: ignore

    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)
except Exception:
    pass
