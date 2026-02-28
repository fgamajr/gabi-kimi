#!/usr/bin/env bash
set -euo pipefail

# Downloads paraphrase-multilingual-MiniLM-L12-v2 ONNX model from HuggingFace.
# Produces files in models/ that OnnxEmbedder needs: model.onnx + vocab.txt

MODEL_DIR="${1:-models/paraphrase-multilingual-MiniLM-L12-v2}"
HF_BASE="https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/resolve/main"

mkdir -p "$MODEL_DIR"

echo "Downloading ONNX model to $MODEL_DIR ..."

# ONNX model (from ONNX subdirectory on HuggingFace)
if [ ! -f "$MODEL_DIR/model.onnx" ]; then
    curl -L "$HF_BASE/onnx/model.onnx" -o "$MODEL_DIR/model.onnx"
    echo "✓ model.onnx downloaded"
else
    echo "✓ model.onnx already exists"
fi

# Vocabulary file for WordPiece tokenizer
if [ ! -f "$MODEL_DIR/vocab.txt" ]; then
    curl -L "$HF_BASE/vocab.txt" -o "$MODEL_DIR/vocab.txt"
    echo "✓ vocab.txt downloaded"
else
    echo "✓ vocab.txt already exists"
fi

# Config files
for f in config.json tokenizer_config.json special_tokens_map.json; do
    if [ ! -f "$MODEL_DIR/$f" ]; then
        curl -sL "$HF_BASE/$f" -o "$MODEL_DIR/$f" 2>/dev/null || true
    fi
done

echo ""
echo "Model ready at: $MODEL_DIR"
echo "  model.onnx  : $(du -sh "$MODEL_DIR/model.onnx" | cut -f1)"
echo "  vocab.txt   : $(du -sh "$MODEL_DIR/vocab.txt" | cut -f1)"
