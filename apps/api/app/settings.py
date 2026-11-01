from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    operator_api_key: str
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    osrm_base: str = "https://router.project-osrm.org"
    cors_origin: str = "http://localhost:3000"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
settings = Settings()
