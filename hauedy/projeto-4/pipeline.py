"""
pipeline.py - Orquestrador Central do Pipeline UDA.

Fluxo completo de execução:
  1. Scraping dos portais de RI → lista de (url_pdf, empresa)
  2. Download de cada PDF
  3. Cálculo do hash SHA-256 (idempotência)
  4. Verificação no catálogo — pula se já processado
  5. Chunking semântico do PDF
  6. Extração via LLM (GPT-4o-mini)
  7. Validação pelo Contrato Semântico (Pydantic)
  8. Persistência no SQLite
  9. Atualização do catálogo com status final

Este módulo pode ser executado diretamente ('python pipeline.py')
ou acionado pelo scheduler.py ou pela API (/api/pipeline/run).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Garante que o diretório raiz está no sys.path quando executado diretamente
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import EMPRESAS
from src.database.repository import init_db, save_many
from src.extraction.catalog import (
    compute_hash,
    init_catalog,
    is_already_processed,
    mark_error,
    mark_success,
    register_pdf,
)
from src.extraction.pdf_parser import semantic_chunks, full_text
from src.extraction.scraper import download_pdf, scrape_all
from src.processing.llm_extractor import extract_from_chunks

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_pipeline() -> dict:
    """
    Executa o pipeline UDA completo.

    Returns:
        Dicionário com estatísticas da execução:
        {
            "pdfs_encontrados": int,
            "pdfs_novos": int,
            "pdfs_ja_processados": int,
            "registros_salvos": int,
            "erros": int,
        }
    """
    stats = {
        "pdfs_encontrados": 0,
        "pdfs_novos": 0,
        "pdfs_ja_processados": 0,
        "registros_salvos": 0,
        "erros": 0,
    }

    logger.info("=" * 60)
    logger.info("🚀 Iniciando Pipeline UDA — Conjuntura Habitacional")
    logger.info("=" * 60)

    # ── 1. Inicialização ───────────────────────────────────────────
    init_db()
    init_catalog()

    # ── 2. Scraping ────────────────────────────────────────────────
    logger.info("📡 Etapa 1/4: Scraping dos portais de RI...")
    pdf_links: list[tuple[str, str]] = scrape_all()
    stats["pdfs_encontrados"] = len(pdf_links)

    if not pdf_links:
        logger.warning("⚠️  Nenhum PDF encontrado. Verifique a conectividade e os URLs das empresas.")
        return stats

    # ── 3. Processamento de cada PDF ───────────────────────────────
    logger.info("⚙️  Etapa 2/4: Processando %d PDF(s)...", len(pdf_links))

    for url, empresa in pdf_links:
        logger.info("─" * 40)
        logger.info("📎 PDF: %s | Empresa: %s", url[:70], empresa)

        # 3a. Download
        pdf_bytes = download_pdf(url)
        if pdf_bytes is None:
            logger.error("❌ Falha no download. Pulando.")
            stats["erros"] += 1
            continue

        # 3b. Hash SHA-256 (idempotência)
        pdf_hash = compute_hash(pdf_bytes)
        logger.info("🔑 SHA-256: %s...", pdf_hash[:16])

        # 3c. Verifica catálogo
        if is_already_processed(pdf_hash):
            logger.info("⏭️  PDF já processado anteriormente. Pulando.")
            stats["pdfs_ja_processados"] += 1
            continue

        # Registra como 'pending' no catálogo
        register_pdf(pdf_hash, url, empresa)
        stats["pdfs_novos"] += 1

        try:
            # 3d. Chunking semântico
            logger.info("🔪 Etapa 3/4: Chunking semântico...")
            chunks = semantic_chunks(pdf_bytes)

            # Fallback: usa full-text se chunking não gerar resultados
            if not chunks:
                logger.warning("Chunking não gerou resultados. Usando full-text como fallback.")
                full = full_text(pdf_bytes)
                if full.strip():
                    chunks = [full[:6000]]  # Limita ao tamanho do contexto

            if not chunks:
                logger.error("❌ Não foi possível extrair texto do PDF.")
                mark_error(pdf_hash, "Texto vazio após parsing.")
                stats["erros"] += 1
                continue

            # 3e. Extração via LLM
            logger.info("🤖 Etapa 4/4: Extração via LLM (%d chunks)...", len(chunks))
            registros = extract_from_chunks(chunks, empresa, url, pdf_hash)

            if not registros:
                logger.warning("⚠️  LLM não extraiu dados relevantes deste PDF.")
                mark_error(pdf_hash, "LLM não retornou dados operacionais.")
                stats["erros"] += 1
                continue

            # 3f. Persistência
            saved = save_many(registros)
            stats["registros_salvos"] += saved
            mark_success(pdf_hash)

            logger.info("✅ %d registro(s) salvo(s) com sucesso.", saved)

        except Exception as exc:
            logger.error("❌ Erro inesperado ao processar PDF: %s", exc, exc_info=True)
            mark_error(pdf_hash, str(exc))
            stats["erros"] += 1

    # ── 4. Relatório final ─────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("🏁 Pipeline concluído!")
    logger.info("   PDFs encontrados   : %d", stats["pdfs_encontrados"])
    logger.info("   PDFs novos         : %d", stats["pdfs_novos"])
    logger.info("   Já processados     : %d", stats["pdfs_ja_processados"])
    logger.info("   Registros salvos   : %d", stats["registros_salvos"])
    logger.info("   Erros              : %d", stats["erros"])
    logger.info("=" * 60)

    return stats


if __name__ == "__main__":
    resultado = run_pipeline()
    print("\nResumo da execução:")
    for chave, valor in resultado.items():
        print(f"  {chave}: {valor}")
