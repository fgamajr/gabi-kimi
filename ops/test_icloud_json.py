import json
import os

# Test writing a JSON file to the configured host-backed archive path
icloud_root = os.getenv("ICLOUD_DATA_PATH") or os.getenv("GABI_DOU_DATA")
if not icloud_root:
    raise SystemExit("Set ICLOUD_DATA_PATH or GABI_DOU_DATA before running this test.")

icloud_path = os.path.join(icloud_root, "test_json_storage")
os.makedirs(icloud_path, exist_ok=True)

test_data = {
    "id": "2002-01-01_DO1_12345",
    "content": "This is a test document saved directly to iCloud.",
    "metadata": {"source": "test", "valid": True}
}

file_path = os.path.join(icloud_path, "test_doc.json")

try:
    with open(file_path, "w") as f:
        json.dump(test_data, f, indent=2)
    print(f"Successfully wrote JSON to {file_path}")
except Exception as e:
    print(f"Failed to write JSON: {e}")
