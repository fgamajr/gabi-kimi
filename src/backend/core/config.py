from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MONGO_STRING: str
    DB_NAME: str = "gabi_dou"
    
    class Config:
        env_file = ".env"

settings = Settings()
