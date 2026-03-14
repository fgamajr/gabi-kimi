# Qwen3 Embedding Server — Mac Setup

Run on your Mac (Apple Silicon) to serve embeddings to the VM.

## 1. Create venv

```bash
cd ~/dev/gabi-kimi/ops/embedding-server
python3 -m venv .venv
source .venv/bin/activate
```

## 2. Install dependencies

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install transformers fastapi uvicorn numpy
```

Note: On Apple Silicon, PyTorch uses the MPS (Metal) backend automatically for GPU acceleration.

## 3. Run the server

```bash
python server.py
```

The model (~1.2GB) downloads on first run. Server starts on `http://0.0.0.0:8900`.

## 4. Test from VM

From the Ubuntu VM:
```bash
curl -X POST http://192.168.15.20:8900/embed \
  -H "Content-Type: application/json" \
  -d '{"texts": ["teste de embedding"], "dimensions": 384}'
```

## 5. Run in background

```bash
nohup python server.py > embed_server.log 2>&1 &
```
