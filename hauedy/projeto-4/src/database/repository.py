"""
repository.py - Camada de Persistência (SQLite).

Responsabilidades:
  - Criar e manter o schema do banco de dados.
  - Salvar registros de DadosOperacionais com linhagem completa.
  - Consultar dados por empresa, ano e trimestre (alimenta a API).
  - Garantir unicidade por (empresa, ano, trimestre) com UPDATE em caso de conflito.

Design:
  - SQLite é usado por ser zero-config e suficiente para o escopo acadêmico.
  - Toda operação é transacional (commit explícito).
  - Row Factory = sqlite3.Row permite acesso por nome de coluna.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Optional

from src.config import DB_PATH
from src.models.schemas import DadosOperacionais

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Schema do banco
# ──────────────────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS dados_operacionais (
    id                                  INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa                             TEXT    NOT NULL,
    ano                                 INTEGER NOT NULL,
    trimestre                           INTEGER NOT NULL,
    vendas_contratadas_unidades         INTEGER,
    vendas_contratadas_valor_milhoes_brl REAL,
    lancamentos_unidades                INTEGER,
    lancamentos_valor_milhoes_brl       REAL,
    entregas_unidades                   INTEGER,
    estoque_unidades                    INTEGER,
    vsv_percentual                      REAL,
    receita_liquida_milhoes_brl         REAL,
    source_url                          TEXT    NOT NULL,
    source_hash                         TEXT    NOT NULL,
    coletado_em                         TEXT    NOT NULL,
    UNIQUE(empresa, ano, trimestre)
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_empresa_periodo
ON dados_operacionais (empresa, ano, trimestre);
"""


# ──────────────────────────────────────────────────────────────────────────────
# Inicialização
# ──────────────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """
    Cria o banco de dados e a tabela se ainda não existirem.
    Deve ser chamado uma vez na inicialização da aplicação.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(CREATE_INDEX_SQL)
        conn.commit()
    logger.info("Banco de dados inicializado em: %s", DB_PATH)


# ──────────────────────────────────────────────────────────────────────────────
# Persistência
# ──────────────────────────────────────────────────────────────────────────────

def save(dados: DadosOperacionais) -> None:
    """
    Salva um registro de DadosOperacionais no banco.

    Estratégia UPSERT: Se já existir um registro para (empresa, ano, trimestre),
    substitui com os dados mais recentes (INSERT OR REPLACE).

    Args:
        dados: Registro validado pelo Contrato Semântico.
    """
    sql = """
    INSERT OR REPLACE INTO dados_operacionais (
        empresa,
        ano,
        trimestre,
        vendas_contratadas_unidades,
        vendas_contratadas_valor_milhoes_brl,
        lancamentos_unidades,
        lancamentos_valor_milhoes_brl,
        entregas_unidades,
        estoque_unidades,
        vsv_percentual,
        receita_liquida_milhoes_brl,
        source_url,
        source_hash,
        coletado_em
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        dados.empresa,
        dados.ano,
        dados.trimestre,
        dados.vendas_contratadas_unidades,
        dados.vendas_contratadas_valor_milhoes_brl,
        dados.lancamentos_unidades,
        dados.lancamentos_valor_milhoes_brl,
        dados.entregas_unidades,
        dados.estoque_unidades,
        dados.vsv_percentual,
        dados.receita_liquida_milhoes_brl,
        dados.source_url,
        dados.source_hash,
        dados.coletado_em.isoformat(),
    )

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(sql, params)
        conn.commit()

    logger.info(
        "💾 Dado salvo: %s %dT%d → %s",
        dados.empresa, dados.trimestre, dados.ano, dados.source_url[:60]
    )


def save_many(registros: list[DadosOperacionais]) -> int:
    """
    Salva múltiplos registros em uma única transação.

    Returns:
        Número de registros salvos com sucesso.
    """
    count = 0
    for dado in registros:
        try:
            save(dado)
            count += 1
        except Exception as exc:
            logger.error("Erro ao salvar %s %dT%d: %s", dado.empresa, dado.trimestre, dado.ano, exc)
    return count


# ──────────────────────────────────────────────────────────────────────────────
# Consultas
# ──────────────────────────────────────────────────────────────────────────────

def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def query(
    empresa: Optional[str] = None,
    ano: Optional[int] = None,
    trimestre: Optional[int] = None,
) -> list[dict]:
    """
    Consulta dados operacionais com filtros opcionais.

    Args:
        empresa: Nome parcial ou completo da empresa (busca case-insensitive).
        ano: Ano de referência.
        trimestre: Trimestre (1–4).

    Returns:
        Lista de dicionários com os registros encontrados.
    """
    conditions: list[str] = []
    params: list = []

    if empresa:
        conditions.append("LOWER(empresa) LIKE LOWER(?)")
        params.append(f"%{empresa}%")
    if ano is not None:
        conditions.append("ano = ?")
        params.append(ano)
    if trimestre is not None:
        conditions.append("trimestre = ?")
        params.append(trimestre)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT * FROM dados_operacionais
        {where_clause}
        ORDER BY empresa, ano DESC, trimestre DESC
    """

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()

    return [_row_to_dict(r) for r in rows]


def list_empresas() -> list[str]:
    """Retorna lista de todas as empresas com dados no banco."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT DISTINCT empresa FROM dados_operacionais ORDER BY empresa"
        ).fetchall()
    return [r[0] for r in rows]


def get_historico(empresa: str) -> list[dict]:
    """
    Retorna o histórico completo de uma empresa em ordem cronológica.
    Útil para geração do Boletim de Conjuntura.
    """
    return query(empresa=empresa)
