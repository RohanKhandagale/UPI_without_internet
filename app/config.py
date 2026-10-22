from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "UPI Offline Mesh"
    packet_max_age_seconds: int = 86400
    idempotency_ttl_seconds: int = 86400
    database_path: str = "upi_mesh.db"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
