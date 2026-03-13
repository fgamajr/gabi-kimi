# GABI DOU - Database Configuration

## MongoDB Connection
**Status**: ✅ Verified & Active  
**Connection String**: `mongodb://localhost:27017/gabi_dou`

### Configuration Details
- **Host**: `localhost` (Ubuntu VM)
- **Port**: `27017` (Default MongoDB port)
- **Database Name**: `gabi_dou`
- **Infrastructure**: Docker Container (`gabi-mongo`) running `mongo:latest`

### Verification
The connection was verified using `ops/test_mongo_connection.py` on 2026-03-11.
- **Server**: Reachable
- **Database**: Exists
- **Collection**: `documents` contains ~298k records (2002 dataset)

### Reasoning for Local Configuration
The decision to keep the local MongoDB connection (`localhost`) instead of a cloud instance (Atlas) is based on:

1.  **Cost Efficiency**: The full 2002-2026 dataset is estimated to be ~100GB. Storing this on MongoDB Atlas would require a paid tier (M30+), costing ~$70-90/mo. The local Docker instance incurs no extra cost.
2.  **Performance**: Ingestion and indexing are significantly faster over the local network (Docker bridge) compared to sending data over the internet to a cloud cluster.
3.  **Hybrid Storage Strategy**:
    - **Metadata & Search Index**: Stored in the local MongoDB (Docker Volume).
    - **Raw Assets (ZIP/XML)**: Stored on **iCloud Drive** (`/media/psf/iCloud/_DATA/gabi_dou`) via Parallels shared folders. This allows:
        - Backup to iCloud.
        - Direct access from macOS for debugging/viewing.
        - Reduced disk pressure on the Ubuntu VM.

### Environment Variables
Ensure your `.env` file matches this configuration:

```bash
# GABI - Configuração Local (Docker + Host)
MONGO_STRING=mongodb://localhost:27017/gabi_dou
DOU_DATA_PATH=/media/psf/iCloud/_DATA/gabi_dou
```

### Docker Status
The database runs in the `gabi-mongo` container:
```bash
docker ps | grep mongo
# Output: 6295ae0c60d4   mongo:latest   ...   0.0.0.0:27017->27017/tcp   gabi-mongo
```
