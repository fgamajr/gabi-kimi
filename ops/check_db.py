from src.backend.data.db import MongoDB
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_db():
    MongoDB.connect()
    client = MongoDB.client
    
    dbs = client.list_database_names()
    logger.info(f"Databases: {dbs}")
    
    for db_name in dbs:
        db = client[db_name]
        stats = db.command("dbStats")
        storage_mb = stats.get('storageSize') / 1024 / 1024
        data_mb = stats.get('dataSize') / 1024 / 1024
        index_mb = stats.get('indexSize') / 1024 / 1024
        logger.info(f"DB: {db_name} - Storage: {storage_mb:.2f} MB, Data: {data_mb:.2f} MB, Index: {index_mb:.2f} MB")
        
        cols = db.list_collection_names()
        for col_name in cols:
             col_stats = db.command("collStats", col_name)
             storage_size = col_stats.get('storageSize') / 1024 / 1024
             count = col_stats.get('count')
             logger.info(f"  - {col_name}: {count} docs, {storage_size:.2f} MB")

if __name__ == "__main__":
    check_db()
