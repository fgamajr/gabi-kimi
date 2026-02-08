#!/usr/bin/env python3
import os
import sys
sys.path.insert(0, 'src')

# Carregar .env via python-dotenv
from dotenv import load_dotenv
load_dotenv('.env')

import uvicorn

if __name__ == "__main__":
    print("🚀 Iniciando GABI API...")
    uvicorn.run("gabi.main:app", host="0.0.0.0", port=8000, reload=False, workers=1)
