import os
from dotenv import load_dotenv

load_dotenv()

SERVER_URL = os.getenv("SERVER_URL")
USER_ID = os.getenv("USER_ID")
DB_PATH = os.getenv("DB_PATH", "farm.db")