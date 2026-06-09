"""
schemas.py - Contrato Semântico do Pipeline UDA.

Este módulo define o esquema Pydantic que atua como "contrato" entre
o LLM e o banco de dados. Ele garante que:
  - O LLM responda EXATAMENTE nos tipos corretos.
  - Valores ausentes sejam tratados como None (NULL no banco).
  - Não haja campos inventados (alucinações).

Campos de linhagem (source_url, source_hash) associam cada linha
ao documento PDF original — requisito de data lineage do projeto.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class DadosOperacionais(BaseModel):
    """
    Esquema central de dados operacionais de uma construtora.
    Representa um único trimestre de uma empresa.
    """

    # ── Identificação temporal ─────────────────────────────────────────
    empresa: str = Field(
        ...,
        description="Nome completo da empresa construtora (ex: 'MRV Engenharia').",
    )
    ano: int = Field(
        ...,
        ge=2000,
        le=2100,
        description="Ano de referência do relatório (ex: 2025).",
    )
    trimestre: int = Field(
        ...,
        ge=1,
        le=4,
        description="Trimestre de referência: 1, 2, 3 ou 4.",
    )

    # ── Vendas Contratadas ─────────────────────────────────────────────
    vendas_contratadas_unidades: Optional[int] = Field(
        None,
        description=(
            "Número ABSOLUTO de unidades vendidas/contratadas no trimestre. "
            "Ignorar percentuais de variação. Se não encontrado, retornar null."
        ),
    )
    vendas_contratadas_valor_milhoes_brl: Optional[float] = Field(
        None,
        description=(
            "Valor total das vendas contratadas em MILHÕES de BRL. "
            "Converter se necessário. Se não encontrado, retornar null."
        ),
    )

    # ── Lançamentos ───────────────────────────────────────────────────
    lancamentos_unidades: Optional[int] = Field(
        None,
        description=(
            "Número ABSOLUTO de unidades lançadas no trimestre. "
            "Ignorar percentuais de variação. Se não encontrado, retornar null."
        ),
    )
    lancamentos_valor_milhoes_brl: Optional[float] = Field(
        None,
        description=(
            "Valor total dos lançamentos em MILHÕES de BRL. "
            "Converter se necessário. Se não encontrado, retornar null."
        ),
    )

    # ── Entregas ──────────────────────────────────────────────────────
    entregas_unidades: Optional[int] = Field(
        None,
        description=(
            "Número ABSOLUTO de unidades entregues (concluídas) no trimestre. "
            "Se não encontrado, retornar null."
        ),
    )

    # ── Estoque e VSV ─────────────────────────────────────────────────
    estoque_unidades: Optional[int] = Field(
        None,
        description=(
            "Total de unidades disponíveis em estoque ao final do trimestre. "
            "Se não encontrado, retornar null."
        ),
    )
    vsv_percentual: Optional[float] = Field(
        None,
        description=(
            "VSV — Velocidade de Vendas sobre Estoque, em porcentagem (%). "
            "Ex: 14.5 para 14,5%. Se não encontrado, retornar null."
        ),
    )

    # ── Dados financeiros adicionais ──────────────────────────────────
    receita_liquida_milhoes_brl: Optional[float] = Field(
        None,
        description=(
            "Receita líquida reconhecida no trimestre em MILHÕES de BRL. "
            "Se não encontrado, retornar null."
        ),
    )

    # ── Linhagem do dado (Data Lineage) ───────────────────────────────
    source_url: str = Field(
        ...,
        description="URL do PDF original da Central de Resultados/RI da empresa.",
    )
    source_hash: str = Field(
        ...,
        description="SHA-256 do conteúdo do PDF — garante idempotência no pipeline.",
    )
    coletado_em: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp UTC de quando o dado foi coletado e processado.",
    )

    # ── Validadores ───────────────────────────────────────────────────
    @field_validator("empresa")
    @classmethod
    def empresa_nao_vazia(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Campo 'empresa' não pode ser vazio.")
        return v

    @field_validator("vendas_contratadas_valor_milhoes_brl", "lancamentos_valor_milhoes_brl", "receita_liquida_milhoes_brl")
    @classmethod
    def valores_positivos(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("Valores monetários não podem ser negativos.")
        return v

    @field_validator("vsv_percentual")
    @classmethod
    def vsv_valido(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0 <= v <= 100):
            raise ValueError("VSV percentual deve estar entre 0 e 100.")
        return v

    model_config = {"json_schema_extra": {"example": {
        "empresa": "MRV Engenharia",
        "ano": 2025,
        "trimestre": 3,
        "vendas_contratadas_unidades": 14500,
        "vendas_contratadas_valor_milhoes_brl": 3200.5,
        "lancamentos_unidades": 12000,
        "lancamentos_valor_milhoes_brl": 2800.0,
        "entregas_unidades": 8500,
        "estoque_unidades": 22000,
        "vsv_percentual": 14.2,
        "receita_liquida_milhoes_brl": 2100.0,
        "source_url": "https://ri.mrv.com.br/resultado-3T25.pdf",
        "source_hash": "abc123...",
        "coletado_em": "2025-11-15T12:00:00",
    }}}


class DadosOperacionaisLista(BaseModel):
    """Wrapper para quando o LLM retornar múltiplos registros num único PDF."""
    registros: list[DadosOperacionais] = Field(
        default_factory=list,
        description="Lista de registros operacionais extraídos do documento.",
    )
