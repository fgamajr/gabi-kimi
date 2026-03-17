import sys
import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

def test_mongo_connection():
    uri = os.getenv("MONGO_STRING", "mongodb://mongo:27017/gabi_dou")
    db_name = os.getenv("DB_NAME", "gabi_dou")
    print(f"Testing connection to: {uri}")
    
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=2000)
        # Force a connection to verify server is available
        client.admin.command('ping')
        print("Successfully connected to MongoDB server.")
        
        # Check database existence
        dbs = client.list_database_names()
        if db_name in dbs:
            print(f"Database '{db_name}' exists.")
            db = client[db_name]
            collections = db.list_collection_names()
            print(f"Collections found: {collections}")
            
            # Check document count in 'documents' collection if it exists
            if "documents" in collections:
                count = db.documents.count_documents({})
                print(f"Document count in 'documents': {count}")
            else:
                print("Collection 'documents' not found.")
        else:
            print(f"Database '{db_name}' does not exist yet (it will be created on first write).")
            
    except ConnectionFailure:
        print("Server not available.")
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_mongo_connection()
