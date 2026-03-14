from pymongo import MongoClient
from src.backend.core.config import settings

class MongoDB:
    client: MongoClient = None
    db = None

    @classmethod
    def connect(cls):
        if cls.client is None:
            cls.client = MongoClient(settings.MONGO_STRING)
            cls.db = cls.client[settings.DB_NAME]
            print("Connected to MongoDB Atlas")

    @classmethod
    def get_db(cls):
        if cls.db is None:
            cls.connect()
        return cls.db

db = MongoDB.get_db()
