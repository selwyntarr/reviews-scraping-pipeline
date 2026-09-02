from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"

    llm_provider: str = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"

    overpass_url: str = "https://overpass-api.de/api/interpreter"
    socrata_app_token: str = ""
    reddit_user_agent: str = "venue-insight-pipeline/0.1 (portfolio project)"


@lru_cache
def settings() -> Settings:
    return Settings()
