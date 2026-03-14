from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MONGO_STRING: str
    DB_NAME: str = "gabi_dou"
    DOU_DATA_PATH: Optional[str] = None
    ICLOUD_DATA_PATH: Optional[str] = None
    PIPELINE_TMP: str = "/tmp/gabi-pipeline"
    ES_URL: str = "http://localhost:9200"
    ES_INDEX: str = "gabi_documents"
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
