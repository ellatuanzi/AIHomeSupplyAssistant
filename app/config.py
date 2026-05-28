from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "家庭 AI 补货助手"
    app_base_url: str = "http://localhost:8000"
    timezone: str = "America/Los_Angeles"

    google_sheet_id: str = ""
    google_credentials_file: str = "credentials/google_oauth_client.json"
    google_token_file: str = "credentials/google_token.json"
    google_oauth_client_json: str = Field(default="", repr=False)
    google_token_json: str = Field(default="", repr=False)
    hsa_sheet_id: str = ""
    hsa_sheet_name: str = "HSA 候选记录"
    hsa_keywords: str = (
        "hsa,fsa,hydrocortisone,anti-itch,first aid,bandage,medicine,medical,"
        "sunscreen,spf,thermometer,covid,allergy,ibuprofen,acetaminophen,"
        "pain relief,antacid,contact lens,saline,eczema"
    )
    gmail_sender_email: str = ""
    daily_summary_to_email: str = ""
    default_shipping_address: str = ""
    order_email_query: str = (
        '(subject:"order received" OR subject:"order confirmation" OR '
        'subject:"your order" OR subject:ordered) '
        '-subject:shipped -subject:delivered -category:promotions newer_than:14d'
    )
    max_order_emails: int = 5

    openai_api_key: str = Field(default="", repr=False)
    openai_model: str = "gpt-4.1-mini"
    openai_timeout_seconds: float = 20

    retail_search_mode: str = "search_urls"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
