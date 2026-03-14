import os
import sys
import subprocess
import datetime

# Add src to path
sys.path.append(os.path.join(os.getcwd()))

from src.backend.core.config import settings

def backup_to_icloud():
    if not settings.DOU_DATA_PATH:
        print("Error: DOU_DATA_PATH not set in .env")
        return

    # Target directory on iCloud
    backup_dir = os.path.join(settings.DOU_DATA_PATH, "mongo_dump")
    os.makedirs(backup_dir, exist_ok=True)
    
    # Timestamp for the backup folder
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    
    archive_file = os.path.join(backup_dir, f"gabi_dou_{timestamp}.archive")
    
    print(f"Streaming backup to: {archive_file}")
    
    try:
        # We pipe the output of 'docker exec' directly to the file
        with open(archive_file, "wb") as f:
            # Note: We need to use 'mongodump' inside the container.
            # The connection string inside container is just localhost:27017
            cmd = ["docker", "exec", "gabi-mongo", "mongodump", "--db", "gabi_dou", "--archive"]
            
            process = subprocess.Popen(cmd, stdout=f, stderr=subprocess.PIPE)
            _, stderr = process.communicate()
            
            if process.returncode != 0:
                print(f"Error dumping database: {stderr.decode()}")
                # If mongodump is not found in container, we might need to install it or use another method
            else:
                print(f"Backup successful: {archive_file}")
                # Also save a small metadata file
                with open(f"{archive_file}.meta", "w") as meta:
                    meta.write(f"Backup of gabi_dou at {timestamp}\n")
                    
    except Exception as e:
        print(f"Backup failed: {e}")

if __name__ == "__main__":
    backup_to_icloud()
