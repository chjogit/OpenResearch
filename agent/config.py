"""환경 변수 읽기. 값은 .env 에 두고 커밋하지 않습니다."""
import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
UPSTAGE_API_KEY = os.getenv("UPSTAGE_API_KEY", "")
SOLAR_MODEL = os.getenv("SOLAR_MODEL", "solar-pro")
AGENT_MODE = os.getenv("AGENT_MODE", "expert")  # expert | guide
