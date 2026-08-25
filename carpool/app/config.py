"""Configuración de la aplicación, cargada desde variables de entorno."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Carpool"
    app_subtitle: str = "Reparto de gastos del coche"

    # Clave de firma de sesiones. Genérala con: openssl rand -hex 32
    secret_key: str = "cambia-esta-clave-en-produccion"

    # sqlite:///./data/carpool.db  |  postgresql+psycopg2://user:pass@db:5432/carpool
    database_url: str = "sqlite:///./data/carpool.db"

    # Servicio de routing OSRM
    osrm_url: str = "http://osrm:5000"
    osrm_profile: str = "driving"

    # Búsqueda de direcciones: "photon" (permite autocompletado) o "nominatim"
    geo_provider: str = "photon"
    photon_url: str = "https://photon.komoot.io"
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    geo_paises: str = "es"
    # Centro del mapa al abrirlo
    mapa_lat: float = 41.1189
    mapa_lon: float = 1.2445
    mapa_zoom: int = 11

    # Administrador inicial (se crea en el primer arranque si no existe)
    admin_email: str = "admin@example.com"
    admin_password: str = "cambiame"
    admin_alias: str = "admin"

    # Cookie segura: ponlo a False solo si sirves por HTTP plano en local
    cookie_secure: bool = True

    # Avisos por Telegram (opcional). Vacío = desactivado.
    telegram_token: str = ""
    telegram_chat_id: str = ""

    # Retención de viajes cancelados/pagados en meses (0 = sin purga)
    retencion_meses: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
