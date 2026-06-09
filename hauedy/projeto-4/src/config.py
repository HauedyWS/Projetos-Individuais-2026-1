"""
config.py - Configurações centralizadas do pipeline UDA.
Lê variáveis de ambiente do arquivo .env.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# === LLM ===
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.0"))

# === Diretórios ===
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PDFS_DIR = DATA_DIR / "pdfs"
DB_PATH = DATA_DIR / "conjuntura.db"

# Garante que os diretórios existam
DATA_DIR.mkdir(exist_ok=True)
PDFS_DIR.mkdir(exist_ok=True)

# === Scraping ===
SCRAPING_INTERVAL_HOURS: int = int(os.getenv("SCRAPING_INTERVAL_HOURS", "24"))
REQUEST_TIMEOUT: int = 30  # segundos
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# === Empresas monitoradas ===
# Adicione/remova empresas conforme necessário.
# Cada entrada: { "nome": str, "ri_url": str }
EMPRESAS = [
    {
        "nome": "MRV",
        "ri_url": "https://ri.mrv.com.br/pt/central-de-resultados",
    },
    {
        "nome": "Cury",
        "ri_url": "https://ri.cury.com.br/pt-BR/central-de-resultados",
    },
]

# === Chunking ===
MAX_CHUNK_CHARS: int = 6000     # Tamanho máximo de cada chunk enviado ao LLM
MAX_TOKENS_RESPONSE: int = 1000 # Máximo de tokens na resposta do LLM
