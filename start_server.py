#!/usr/bin/env python3
"""Simple HTTP server for GABI API."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "gabi.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        workers=1,
    )
