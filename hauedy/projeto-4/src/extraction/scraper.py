"""
scraper.py - Módulo de Coleta Automatizada (Web Scraping).

Responsabilidades:
  - Navegar nos portais de Relações com Investidores (RI) das construtoras.
  - Detectar novos PDFs de Prévias Operacionais e Relatórios de Conjuntura.
  - Retornar lista de (url, empresa) para processamento.

Estratégia de gatilho: Polling agendado (CronJob).
  O scheduler.py chama este módulo periodicamente (padrão: 1x ao dia),
  evitando sobrecarga nos servidores das empresas.

Empresas suportadas:
  - MRV Engenharia   (ri.mrv.com.br)
  - Cury Construtora (ri.cury.com.br)

Resiliência: O scraper usa um conjunto de seletores CSS/texto por empresa,
com fallback para busca genérica de links .pdf na página, garantindo que
o pipeline continue funcionando mesmo se o layout do site mudar.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.config import EMPRESAS, REQUEST_HEADERS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Palavras-chave para identificar documentos relevantes
# ──────────────────────────────────────────────────────────────────────────────
KEYWORDS_RELEVANTES = [
    "prévia operacional",
    "previa operacional",
    "resultado",
    "conjuntura",
    "operacional",
    "trimest",
    "release",
    "1t", "2t", "3t", "4t",
    "1q", "2q", "3q", "4q",
]


def _is_relevant_link(text: str, href: str) -> bool:
    """
    Heurística para identificar se um link aponta para um relatório relevante.
    Verifica tanto o texto do link quanto a URL.
    """
    combined = (text + " " + href).lower()
    has_keyword = any(kw in combined for kw in KEYWORDS_RELEVANTES)
    is_pdf = href.lower().endswith(".pdf") or "pdf" in href.lower()
    return has_keyword or is_pdf


def _fetch_page(url: str) -> Optional[BeautifulSoup]:
    """
    Realiza requisição HTTP com tratamento de erros e retorna o BeautifulSoup
    da página. Retorna None se houver falha.
    """
    try:
        response = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except requests.exceptions.RequestException as exc:
        logger.warning("Falha ao acessar URL '%s': %s", url, exc)
        return None


def _extract_pdf_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """
    Extrai todas as URLs de PDF de uma página HTML.
    Prioriza links com palavras-chave de relatórios operacionais.
    """
    pdf_links: list[str] = []

    for tag in soup.find_all("a", href=True):
        href: str = tag["href"]
        text: str = tag.get_text(strip=True)

        # Monta URL absoluta
        if not href.startswith("http"):
            href = urljoin(base_url, href)

        # Só coleta PDFs diretamente linkados ou links relevantes
        if href.lower().endswith(".pdf"):
            if _is_relevant_link(text, href):
                pdf_links.append(href)
        elif _is_relevant_link(text, href) and not href.endswith(("#", "javascript:void(0)")):
            # Pode ser uma sub-página com relatórios — rastreia 1 nível abaixo
            sub_soup = _fetch_page(href)
            if sub_soup:
                for sub_tag in sub_soup.find_all("a", href=True):
                    sub_href: str = sub_tag["href"]
                    if not sub_href.startswith("http"):
                        sub_href = urljoin(href, sub_href)
                    if sub_href.lower().endswith(".pdf"):
                        pdf_links.append(sub_href)
                time.sleep(0.5)  # Cortesia: evita flood no servidor

    return list(dict.fromkeys(pdf_links))  # Remove duplicatas mantendo ordem


# ──────────────────────────────────────────────────────────────────────────────
# Scrapers por empresa (podem ter lógica específica)
# ──────────────────────────────────────────────────────────────────────────────

def _scrape_empresa(empresa: dict) -> list[tuple[str, str]]:
    """
    Executa o scraping da Central de Resultados de uma empresa.

    Args:
        empresa: Dict com chaves 'nome' e 'ri_url'.

    Returns:
        Lista de tuplas (url_pdf, nome_empresa).
    """
    nome: str = empresa["nome"]
    ri_url: str = empresa["ri_url"]

    logger.info("🔍 Iniciando scraping: %s → %s", nome, ri_url)
    soup = _fetch_page(ri_url)

    if soup is None:
        logger.error("❌ Não foi possível acessar o portal RI de %s.", nome)
        return []

    pdf_links = _extract_pdf_links(soup, ri_url)
    logger.info("✅ %s: encontrado(s) %d link(s) de PDF.", nome, len(pdf_links))

    return [(url, nome) for url in pdf_links]


def scrape_all() -> list[tuple[str, str]]:
    """
    Executa o scraping de todas as empresas configuradas em EMPRESAS (config.py).

    Returns:
        Lista de tuplas (url_pdf, nome_empresa) de todos os portais.
    """
    all_results: list[tuple[str, str]] = []

    for empresa in EMPRESAS:
        try:
            results = _scrape_empresa(empresa)
            all_results.extend(results)
        except Exception as exc:
            logger.error("Erro inesperado ao scraping de %s: %s", empresa["nome"], exc)
        time.sleep(1)  # Pausa entre empresas

    logger.info("🏁 Scraping finalizado. Total de PDFs encontrados: %d", len(all_results))
    return all_results


def download_pdf(url: str) -> Optional[bytes]:
    """
    Faz o download do conteúdo binário de um PDF.

    Args:
        url: URL do PDF.

    Returns:
        Bytes do PDF ou None em caso de erro.
    """
    try:
        logger.info("⬇️  Baixando PDF: %s", url)
        response = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT * 2,
            stream=True,
        )
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
            logger.warning("URL não parece ser um PDF (Content-Type: %s): %s", content_type, url)

        return response.content

    except requests.exceptions.RequestException as exc:
        logger.error("❌ Falha ao baixar PDF '%s': %s", url, exc)
        return None
