"""
pdf_parser.py - Extração de Texto e Chunking Semântico de PDFs.

Estratégia adotada: CHUNKING SEMÂNTICO
  Em vez de enviar o PDF inteiro para o LLM (estratégia Full-Scan),
  dividimos o documento em blocos menores orientados por contexto.

  Justificativa:
    - Relatórios de RI podem ter 30-100 páginas, excedendo janelas de contexto.
    - O chunking reduz custo de tokens e latência.
    - Chunks semânticos preservam a coerência das tabelas de dados.

  Algoritmo:
    1. Extrai texto de cada página com PyMuPDF (fitz).
    2. Identifica "seções de interesse" por regex (Vendas, Lançamentos, etc.).
    3. Agrupa páginas vizinhas em chunks de tamanho controlado.
    4. Cada chunk é enviado separadamente ao LLM para extração.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import fitz  # PyMuPDF

from src.config import MAX_CHUNK_CHARS

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Padrões semânticos para identificar seções relevantes
# ──────────────────────────────────────────────────────────────────────────────
_SECTION_HEADERS = re.compile(
    r"(?i)("
    r"vendas?\s+contratadas?|"
    r"lançamentos?|"
    r"entregas?|"
    r"estoque\s+disponível|"
    r"vsv|velocidade\s+de\s+vendas|"
    r"prévia\s+operacional|"
    r"destaques?\s+operacionais?|"
    r"resultados?\s+operacionais?|"
    r"receita\s+(líquida|bruta)|"
    r"\d{1,2}[ºoT°]\s*(trimestre|trim\.?|[TQ]\d)|"
    r"\d{4}\s*/\s*\d{1,2}[TQ]"
    r")"
)

_TABLE_INDICATORS = re.compile(
    r"(?i)(r\$|mil|mhes?|milhões?|units?|unid\.?|\bm²\b|%\s*aa|\bvso\b)"
)


# ──────────────────────────────────────────────────────────────────────────────
# Extração de texto
# ──────────────────────────────────────────────────────────────────────────────

def extract_pages(pdf_bytes: bytes) -> list[dict]:
    """
    Extrai o texto de cada página do PDF.

    Args:
        pdf_bytes: Conteúdo binário do PDF.

    Returns:
        Lista de dicts com {'page': int, 'text': str, 'score': int}.
        O campo 'score' indica relevância da página (quantos padrões foram encontrados).
    """
    pages: list[dict] = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        logger.info("📄 PDF aberto: %d páginas.", doc.page_count)

        for i, page in enumerate(doc):
            text = page.get_text("text")
            # Pontua a página por relevância
            score = len(_SECTION_HEADERS.findall(text)) + len(_TABLE_INDICATORS.findall(text))
            pages.append({"page": i + 1, "text": text, "score": score})

        doc.close()
    except Exception as exc:
        logger.error("Erro ao processar PDF com PyMuPDF: %s", exc)

    return pages


# ──────────────────────────────────────────────────────────────────────────────
# Chunking Semântico
# ──────────────────────────────────────────────────────────────────────────────

def semantic_chunks(pdf_bytes: bytes, min_score: int = 1) -> list[str]:
    """
    Divide o PDF em chunks semânticos focados em dados operacionais.

    Algoritmo:
      1. Filtra páginas com score >= min_score (contêm dados relevantes).
      2. Agrupa páginas vizinhas em blocos de tamanho <= MAX_CHUNK_CHARS.
      3. Cada chunk inclui o número de página para rastreabilidade.

    Args:
        pdf_bytes: Bytes do PDF.
        min_score: Score mínimo para considerar uma página relevante.

    Returns:
        Lista de strings (chunks) prontas para envio ao LLM.
    """
    pages = extract_pages(pdf_bytes)

    if not pages:
        return []

    # Filtra páginas relevantes; se nenhuma passar no filtro, usa todas
    relevant = [p for p in pages if p["score"] >= min_score]
    if not relevant:
        logger.warning("Nenhuma página relevante encontrada (score >= %d). Usando todas.", min_score)
        relevant = pages

    logger.info(
        "🔪 Chunking: %d de %d páginas selecionadas (score >= %d).",
        len(relevant), len(pages), min_score
    )

    # Agrupa em chunks por tamanho máximo
    chunks: list[str] = []
    current_chunk = ""

    for page_data in relevant:
        page_header = f"\n\n[Página {page_data['page']}]\n"
        block = page_header + page_data["text"]

        if len(current_chunk) + len(block) > MAX_CHUNK_CHARS:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            current_chunk = block
        else:
            current_chunk += block

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    logger.info("✅ Gerados %d chunk(s) semânticos.", len(chunks))
    return chunks


def full_text(pdf_bytes: bytes) -> str:
    """
    Estratégia Full-Scan: retorna o texto completo do PDF como string única.
    Usado como fallback quando o chunking não produz resultados.

    Args:
        pdf_bytes: Bytes do PDF.

    Returns:
        Texto completo concatenado de todas as páginas.
    """
    pages = extract_pages(pdf_bytes)
    return "\n\n".join(
        f"[Página {p['page']}]\n{p['text']}" for p in pages
    )
