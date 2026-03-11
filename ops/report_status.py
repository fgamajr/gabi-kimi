from src.backend.data.db import MongoDB
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def report_status():
    MongoDB.connect()
    db = MongoDB.get_db()
    collection = db["documents"]
    
    total_docs = collection.count_documents({})
    logger.info(f"Total Documents: {total_docs}")
    
    # Aggregation to count by month
    pipeline = [
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$pub_date"},
                    "month": {"$month": "$pub_date"}
                },
                "count": {"$sum": 1}
            }
        },
        {"$sort": {"_id.year": 1, "_id.month": 1}}
    ]
    
    results = collection.aggregate(pipeline)
    logger.info("Documents by Month:")
    for result in results:
        y = result["_id"]["year"]
        m = result["_id"]["month"]
        c = result["count"]
        logger.info(f" - {y}-{m:02d}: {c} docs")

if __name__ == "__main__":
    report_status()
