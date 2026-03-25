import os
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseModel):
    GEMINI_API_KEY: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    MATHPIX_APP_ID: str = Field(default_factory=lambda: os.getenv("MATHPIX_APP_ID", ""))
    MATHPIX_APP_KEY: str = Field(default_factory=lambda: os.getenv("MATHPIX_APP_KEY", ""))
    PORT: int = Field(default=8020)
    HOST: str = Field(default="0.0.0.0")

settings = Settings()
