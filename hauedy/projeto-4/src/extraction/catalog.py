"""
catalog.py - Catálogo de Dados e Linhagem (Data Catalog & Data Lineage).

Responsabilidades:
  1. Calcular o hash SHA-256 de cada PDF para garantir idempotência.
  2. Verificar se um documento já foi processado (evitar reprocessamento e
     custos desnecessários de API).
  3. Registrar a linhagem do dado: associa cada documento ao URL de origem,
     empresa, timestamp e status de processamento.

Esta camada é o "guardião" do pipeline: nenhum PDF passa para o LLM
sem antes ser verificado aqui.
"""
from __future__ import annotations

import hashlib
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import DB_PATH

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Funções de Hash
# ──────────────────────────────────────────────────────────────────────────────

def compute_hash(content: bytes) -> str:
    """
    Calcula o hash SHA-256 do conteúdo binário de um PDF.

    O SHA-256 é usado em vez de MD5 por ser criptograficamente mais robusto,
    eliminando riscos de colisão acidental entre documentos distintos.

    Args:
        content: Bytes do arquivo PDF.

    Returns:
        String hexadecimal de 64 caracteres representando o hash SHA-256.
    """
    return hashlib.sha256(content).hexdigest()


# ──────────────────────────────────────────────────────────────────────────────
# Inicialização do Catálogo
# ──────────────────────────────────────────────────────────────────────────────

def init_catalog() -> None:
    """
    Inicializa a tabela de catálogo no banco SQLite.
    Deve ser chamada uma vez na inicialização do pipeline.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS catalog_pdfs (
                hash          TEXT PRIMARY KEY,
                url           TEXT NOT NULL,
                empresa       TEXT,
                status        TEXT NOT NULL DEFAULT 'pending',
                processado_em TEXT,
                erro          TEXT
            )
        """)
        conn.commit()
    logger.info("Catálogo de dados inicializado em: %s", DB_PATH)


# ──────────────────────────────────────────────────────────────────────────────
# Verificação de Idempotência
# ──────────────────────────────────────────────────────────────────────────────

def is_already_processed(pdf_hash: str) -> bool:
    """
    Verifica se um PDF já foi processado com sucesso anteriormente.

    Args:
        pdf_hash: SHA-256 do PDF.

    Returns:
        True se já processado (status='success'), False caso contrário.
    """
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT status FROM catalog_pdfs WHERE hash = ? AND status = 'success'",
            (pdf_hash,),
        ).fetchone()
    return row is not None


def register_pdf(pdf_hash: str, url: str, empresa: str) -> None:
    """
    Registra um novo PDF no catálogo com status 'pending'.
    Ignora silenciosamente se o hash já existir (INSERT OR IGNORE).

    Args:
        pdf_hash: SHA-256 do PDF.
        url: URL de onde o PDF foi obtido.
        empresa: Nome da empresa a qual o relatório pertence.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO catalog_pdfs (hash, url, empresa, status)
            VALUES (?, ?, ?, 'pending')
            """,
            (pdf_hash, url, empresa),
        )
        conn.commit()
    logger.debug("PDF registrado no catálogo: hash=%s empresa=%s", pdf_hash[:12], empresa)


def mark_success(pdf_hash: str) -> None:
    """Atualiza o status do PDF para 'success' após extração bem-sucedida."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE catalog_pdfs
            SET status = 'success', processado_em = ?
            WHERE hash = ?
            """,
            (datetime.utcnow().isoformat(), pdf_hash),
        )
        conn.commit()


def mark_error(pdf_hash: str, error_msg: str) -> None:
    """Registra um erro de processamento no catálogo para rastreabilidade."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE catalog_pdfs
            SET status = 'error', processado_em = ?, erro = ?
            WHERE hash = ?
            """,
            (datetime.utcnow().isoformat(), error_msg[:500], pdf_hash),
        )
        conn.commit()
    logger.warning("Erro registrado no catálogo: hash=%s erro=%s", pdf_hash[:12], error_msg[:80])


def list_catalog() -> list[dict]:
    """Retorna todos os registros do catálogo como lista de dicionários."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM catalog_pdfs ORDER BY processado_em DESC"
        ).fetchall()
    return [dict(r) for r in rows]
