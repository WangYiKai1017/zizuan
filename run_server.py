"""Entry point for the Agent Service.

Usage:
    python run_server.py
    
Or with uvicorn directly:
    uvicorn run_server:app --host 0.0.0.0 --port 8000 --reload
"""
import uvicorn

from src.service.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "run_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
