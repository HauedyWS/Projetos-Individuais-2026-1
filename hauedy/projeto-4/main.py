"""
main.py - Ponto de entrada da API FastAPI.

Uso:
  uvicorn main:app --reload --port 8000

Acesse a documentação interativa em:
  http://localhost:8000/docs   (Swagger UI)
  http://localhost:8000/redoc  (ReDoc)
"""
import logging
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.api.routes import app  # noqa: F401 — expõe 'app' para uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
