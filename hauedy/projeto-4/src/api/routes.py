"""
routes.py - Camada de Serviço (API REST/JSON) via FastAPI.

Endpoints disponíveis:
  GET  /api/conjuntura          — Lista dados com filtros opcionais
  GET  /api/conjuntura/empresas — Lista empresas com dados disponíveis
  GET  /api/conjuntura/historico/{empresa} — Histórico completo de uma empresa
  GET  /api/catalogo            — Lista o catálogo de PDFs processados
  POST /api/pipeline/run        — Dispara execução manual do pipeline
  GET  /health                  — Health check

Contrato da API:
  - Todos os endpoints retornam JSON.
  - Parâmetros de query são opcionais; sem filtros, retorna todos os dados.
  - Empresa é buscada de forma case-insensitive e com correspondência parcial.
  - Cada registro inclui source_url e source_hash para rastreabilidade completa.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.database import repository
from src.extraction.catalog import list_catalog, init_catalog
from src.database.repository import init_db

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Inicialização do App FastAPI
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Pipeline UDA — Conjuntura Habitacional",
    description=(
        "API REST para consulta de dados operacionais do setor habitacional brasileiro, "
        "extraídos automaticamente de relatórios e prévias operacionais em PDF das "
        "principais construtoras do país."
    ),
    version="1.0.0",
    contact={
        "name": "Hauedy",
        "url": "https://github.com/unb-Sistemas-de-Machine-learning/Projetos-Individuais-2026-1",
    },
    license_info={"name": "MIT"},
)

# CORS — permite acesso de qualquer origem (ajustável para produção)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    """Inicializa banco e catálogo na startup da aplicação."""
    init_db()
    init_catalog()
    logger.info("✅ API iniciada — banco e catálogo prontos.")


# ──────────────────────────────────────────────────────────────────────────────
# Health Check
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Status"], summary="Health Check")
def health() -> dict:
    """Verifica se a API está operacional."""
    return {"status": "ok", "version": "1.0.0"}


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints de Conjuntura
# ──────────────────────────────────────────────────────────────────────────────

@app.get(
    "/api/conjuntura",
    tags=["Conjuntura"],
    summary="Consulta dados operacionais",
    response_description="Lista de registros operacionais filtrados",
)
def get_conjuntura(
    empresa: Optional[str] = Query(
        None,
        description="Nome (parcial ou completo) da construtora. Ex: 'MRV', 'Cury'.",
        example="MRV",
    ),
    ano: Optional[int] = Query(
        None,
        description="Ano de referência do relatório.",
        example=2025,
        ge=2000,
        le=2100,
    ),
    trimestre: Optional[int] = Query(
        None,
        description="Trimestre de referência (1 a 4).",
        example=3,
        ge=1,
        le=4,
    ),
) -> dict[str, Any]:
    """
    Retorna dados operacionais do setor habitacional com filtros opcionais.

    **Exemplo:** `GET /api/conjuntura?empresa=MRV&ano=2025&trimestre=3`

    Campos retornados por registro:
    - `empresa`, `ano`, `trimestre` — identificação temporal
    - `vendas_contratadas_unidades`, `lancamentos_unidades`, `entregas_unidades` — métricas absolutas
    - `vsv_percentual` — velocidade de vendas
    - `source_url`, `source_hash` — linhagem do dado (link do PDF original)
    - `coletado_em` — timestamp de coleta
    """
    try:
        registros = repository.query(empresa=empresa, ano=ano, trimestre=trimestre)
    except Exception as exc:
        logger.error("Erro na consulta ao banco: %s", exc)
        raise HTTPException(status_code=500, detail="Erro interno ao consultar dados.")

    return {
        "total": len(registros),
        "filtros": {"empresa": empresa, "ano": ano, "trimestre": trimestre},
        "dados": registros,
    }


@app.get(
    "/api/conjuntura/empresas",
    tags=["Conjuntura"],
    summary="Lista empresas disponíveis",
)
def get_empresas() -> dict[str, Any]:
    """Retorna a lista de todas as construtoras com dados disponíveis no banco."""
    try:
        empresas = repository.list_empresas()
    except Exception as exc:
        logger.error("Erro ao listar empresas: %s", exc)
        raise HTTPException(status_code=500, detail="Erro interno.")

    return {"total": len(empresas), "empresas": empresas}


@app.get(
    "/api/conjuntura/historico/{empresa}",
    tags=["Conjuntura"],
    summary="Histórico completo de uma empresa",
)
def get_historico(empresa: str) -> dict[str, Any]:
    """
    Retorna todos os trimestres disponíveis para uma empresa específica,
    em ordem cronológica. Útil para geração do Boletim de Conjuntura.

    **Exemplo:** `GET /api/conjuntura/historico/MRV`
    """
    try:
        historico = repository.get_historico(empresa=empresa)
    except Exception as exc:
        logger.error("Erro ao buscar histórico de %s: %s", empresa, exc)
        raise HTTPException(status_code=500, detail="Erro interno.")

    if not historico:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum dado encontrado para a empresa '{empresa}'.",
        )

    return {
        "empresa": empresa,
        "total_trimestres": len(historico),
        "historico": historico,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints de Catálogo (Data Lineage)
# ──────────────────────────────────────────────────────────────────────────────

@app.get(
    "/api/catalogo",
    tags=["Catálogo"],
    summary="Lista catálogo de PDFs processados",
)
def get_catalogo() -> dict[str, Any]:
    """
    Retorna o catálogo completo de documentos PDF processados pelo pipeline,
    incluindo status (success/error/pending) e timestamp de processamento.

    Implementa Data Lineage: cada linha do banco pode ser rastreada até o
    documento PDF original via `source_url` e `source_hash`.
    """
    try:
        catalogo = list_catalog()
    except Exception as exc:
        logger.error("Erro ao listar catálogo: %s", exc)
        raise HTTPException(status_code=500, detail="Erro interno.")

    return {"total": len(catalogo), "catalogo": catalogo}


# ──────────────────────────────────────────────────────────────────────────────
# Endpoint de Acionamento Manual do Pipeline
# ──────────────────────────────────────────────────────────────────────────────

@app.post(
    "/api/pipeline/run",
    tags=["Pipeline"],
    summary="Dispara execução manual do pipeline",
    status_code=202,
)
def run_pipeline_manually(background_tasks: BackgroundTasks) -> dict:
    """
    Aciona manualmente o pipeline de coleta e processamento em background.
    Retorna imediatamente com status 202 (Accepted) enquanto o pipeline roda.

    Útil para testes sem precisar aguardar o próximo ciclo do scheduler.
    """
    try:
        from pipeline import run_pipeline
        background_tasks.add_task(run_pipeline)
        return {
            "status": "aceito",
            "message": "Pipeline iniciado em background. Verifique /api/conjuntura após alguns instantes.",
        }
    except Exception as exc:
        logger.error("Erro ao iniciar pipeline manualmente: %s", exc)
        raise HTTPException(status_code=500, detail=f"Erro ao iniciar pipeline: {exc}")
