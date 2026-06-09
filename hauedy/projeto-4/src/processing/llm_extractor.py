"""
llm_extractor.py - Motor de Extração com LLM (OpenAI GPT-4o-mini).

Responsabilidades:
  1. Montar o prompt do sistema com o Contrato Semântico.
  2. Enviar chunks do PDF ao LLM com instrução de extração estruturada.
  3. Validar a resposta usando o schema Pydantic (DadosOperacionais).
  4. Agregar resultados de múltiplos chunks de um mesmo PDF.

Proteções contra alucinações (Contrato Semântico):
  - O System Prompt instrui o LLM a responder APENAS em JSON válido.
  - Campos não encontrados DEVEM ser retornados como null.
  - O LLM é proibido de inventar ou interpolar valores.
  - O prompt pede valores ABSOLUTOS, ignorando variações percentuais de marketing.

Modelo: GPT-4o-mini (configurável via LLM_MODEL em .env).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from openai import OpenAI
from pydantic import ValidationError

from src.config import LLM_MODEL, LLM_TEMPERATURE, MAX_TOKENS_RESPONSE, OPENAI_API_KEY
from src.models.schemas import DadosOperacionais

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# System Prompt — Contrato Semântico
# ──────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
Você é um especialista em análise de dados do setor de construção civil brasileiro.
Sua tarefa é extrair dados operacionais estruturados de trechos de relatórios e prévias operacionais de construtoras.

## REGRAS OBRIGATÓRIAS (Contrato Semântico):

1. **Responda SOMENTE em JSON válido**, sem texto adicional, markdown ou explicações.
2. **Valores absolutos**: Extraia APENAS valores numéricos absolutos (ex: 14.500 unidades, R$ 3,2 bilhões). 
   IGNORE percentuais de variação como "+15% vs 2T24" — esses são dados de marketing, não dados brutos.
3. **Valores ausentes**: Se um campo não for encontrado no texto, retorne `null`. NUNCA invente ou estime valores.
4. **Sem alucinações**: Não extrapole, não interpole, não deduza. Se não estiver explícito no texto, é `null`.
5. **Conversão de unidades**: 
   - Valores em "R$ bilhões" → converta para milhões (ex: R$ 3,2 bi = 3200 milhões).
   - Valores em "R$ mil" → converta para milhões dividindo por 1000.
6. **Trimestre e Ano**: Identifique o período de referência do relatório, não a data de publicação.
7. **Empresa**: Use o nome oficial da construtora, não abreviações genéricas.

## FORMATO DE RESPOSTA:
```json
{
  "empresa": "Nome da Empresa",
  "ano": 2025,
  "trimestre": 3,
  "vendas_contratadas_unidades": 14500,
  "vendas_contratadas_valor_milhoes_brl": 3200.5,
  "lancamentos_unidades": 12000,
  "lancamentos_valor_milhoes_brl": 2800.0,
  "entregas_unidades": 8500,
  "estoque_unidades": 22000,
  "vsv_percentual": 14.2,
  "receita_liquida_milhoes_brl": null
}
```

Se o trecho não contiver dados operacionais relevantes, retorne:
```json
{"empresa": null, "ano": null, "trimestre": null}
```
""".strip()


# ──────────────────────────────────────────────────────────────────────────────
# Cliente OpenAI
# ──────────────────────────────────────────────────────────────────────────────

def _get_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise EnvironmentError(
            "OPENAI_API_KEY não configurada. "
            "Adicione sua chave ao arquivo .env (veja .env.example)."
        )
    return OpenAI(api_key=OPENAI_API_KEY)


# ──────────────────────────────────────────────────────────────────────────────
# Extração por chunk
# ──────────────────────────────────────────────────────────────────────────────

def _extract_from_chunk(
    client: OpenAI,
    chunk: str,
    empresa_hint: str,
    source_url: str,
    source_hash: str,
) -> Optional[DadosOperacionais]:
    """
    Envia um chunk de texto ao LLM e tenta extrair um DadosOperacionais.

    Args:
        client: Cliente OpenAI.
        chunk: Texto do chunk a ser analisado.
        empresa_hint: Nome da empresa (dica contextual para o LLM).
        source_url: URL do PDF para linhagem.
        source_hash: SHA-256 do PDF para idempotência.

    Returns:
        DadosOperacionais validado pelo Pydantic, ou None se extração falhar.
    """
    user_message = (
        f"Empresa de referência (dica): {empresa_hint}\n\n"
        f"Trecho do relatório:\n\n{chunk}"
    )

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            max_tokens=MAX_TOKENS_RESPONSE,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        raw_json = response.choices[0].message.content
        data = json.loads(raw_json)

        # Verificação rápida: se o LLM indicou que não havia dados relevantes
        if data.get("empresa") is None and data.get("ano") is None:
            return None

        # Injeta campos de linhagem que o LLM não deve inferir
        data["source_url"] = source_url
        data["source_hash"] = source_hash

        # Validação pelo Contrato Semântico (Pydantic)
        return DadosOperacionais(**data)

    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Resposta do LLM não é JSON válido: %s", exc)
        return None
    except ValidationError as exc:
        logger.warning("Resposta do LLM falhou na validação Pydantic: %s", exc)
        return None
    except Exception as exc:
        logger.error("Erro inesperado na chamada ao LLM: %s", exc)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Extração completa de um PDF (múltiplos chunks)
# ──────────────────────────────────────────────────────────────────────────────

def extract_from_chunks(
    chunks: list[str],
    empresa: str,
    source_url: str,
    source_hash: str,
) -> list[DadosOperacionais]:
    """
    Processa todos os chunks de um PDF e consolida os resultados.

    Estratégia de consolidação:
      - Extrai dados de cada chunk independentemente.
      - Agrupa resultados pelo par (empresa, ano, trimestre).
      - Em caso de conflito entre chunks, o primeiro valor não-nulo prevalece.

    Args:
        chunks: Lista de chunks semânticos do PDF.
        empresa: Nome da empresa (para dica contextual ao LLM).
        source_url: URL de origem do PDF.
        source_hash: SHA-256 do PDF.

    Returns:
        Lista de DadosOperacionais consolidados (usualmente 1 por PDF).
    """
    if not chunks:
        logger.warning("Nenhum chunk para processar.")
        return []

    client = _get_client()
    extracted: list[DadosOperacionais] = []

    for i, chunk in enumerate(chunks, 1):
        logger.info("🤖 Processando chunk %d/%d com %s...", i, len(chunks), LLM_MODEL)
        result = _extract_from_chunk(client, chunk, empresa, source_url, source_hash)
        if result:
            extracted.append(result)

    # Consolidação: agrupa por (empresa, ano, trimestre)
    consolidated: dict[tuple, DadosOperacionais] = {}
    for item in extracted:
        key = (item.empresa.lower(), item.ano, item.trimestre)
        if key not in consolidated:
            consolidated[key] = item
        else:
            # Preenche campos nulos com dados de chunks posteriores
            existing = consolidated[key]
            for field in item.model_fields:
                if getattr(existing, field) is None and getattr(item, field) is not None:
                    setattr(existing, field, getattr(item, field))

    final = list(consolidated.values())
    logger.info(
        "✅ Extração concluída: %d registro(s) consolidado(s) de %d chunk(s).",
        len(final), len(chunks)
    )
    return final
