from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    service_name: str = "demo-item-service"


settings = Settings()
