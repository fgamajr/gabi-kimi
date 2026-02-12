import os
from huggingface_hub import snapshot_download

model_id = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
cache_dir = "./data/tei/cache"

print(f"Downloading {model_id} to {cache_dir}...")
snapshot_download(repo_id=model_id, local_dir=cache_dir, local_dir_use_symlinks=False)
print("Download complete.")
