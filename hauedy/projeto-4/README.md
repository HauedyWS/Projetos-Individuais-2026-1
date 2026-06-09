# Pipeline UDA — Conjuntura Habitacional

Projeto Individual 4 — Sistemas de Machine Learning (UnB, 2026/1)  
**Aluno:** Hauedy  

---

## Visão Geral

Pipeline de **Análise de Dados Não Estruturados (UDA)** focado no setor habitacional brasileiro. O sistema coleta automaticamente PDFs de **Prévias Operacionais** publicados nos portais de Relações com Investidores (RI) das principais construtoras, extrai dados operacionais usando **LLM (GPT-4o-mini)** e os disponibiliza via **API REST**.

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                    PIPELINE UDA                             │
│                                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────┐  │
│  │ Scraper  │───▶│  Catálogo│───▶│  Parser  │───▶│ LLM  │  │
│  │(Polling) │    │(SHA-256) │    │(Chunking)│    │GPT4o │  │
│  └──────────┘    └──────────┘    └──────────┘    └──┬───┘  │
│                                                      │       │
│                  ┌──────────┐    ┌──────────┐        │       │
│                  │  FastAPI │◀───│  SQLite  │◀───────┘       │
│                  │   REST   │    │   (DB)   │               │
│                  └──────────┘    └──────────┘               │
└─────────────────────────────────────────────────────────────┘
```

### Três Camadas Obrigatórias

| Camada | Implementação | Arquivo |
|---|---|---|
| **Extração de Dados** | PyMuPDF + Chunking Semântico | `src/extraction/pdf_parser.py` |
| **Contrato Semântico** | Pydantic + System Prompt blindado | `src/models/schemas.py` + `src/processing/llm_extractor.py` |
| **Catálogo e Linhagem** | SHA-256 + SQLite (data lineage) | `src/extraction/catalog.py` |

---

## Empresas Monitoradas

| Empresa | Portal RI |
|---|---|
| MRV Engenharia | ri.mrv.com.br/pt/central-de-resultados |
| Cury Construtora | ri.cury.com.br/pt-BR/central-de-resultados |

---

## Estratégia Técnica

### Gatilho de Ingestão: Polling Agendado
- O `scheduler.py` executa o pipeline em intervalos configuráveis (padrão: 24h).
- Evita sobrecarga nos servidores das construtoras.

### Idempotência (Evitar Duplicidade)
- Antes de processar qualquer PDF, o sistema calcula seu **hash SHA-256**.
- Se o hash já existir no catálogo com status `success`, o arquivo é ignorado.
- Isso **elimina custos desnecessários de API** com reprocessamento.

### Estratégia de Chunking Semântico
- Documentos são divididos em blocos por seções de interesse (Vendas, Lançamentos, etc.).
- Apenas páginas com pontuação de relevância ≥ 1 são enviadas ao LLM.
- Fallback para full-scan se nenhuma página passar no filtro.

### Contrato Semântico
- O System Prompt instrui o LLM a responder **apenas em JSON válido**.
- Campos ausentes → `null` (nunca inventados).
- Extração de **valores absolutos** (ignora variações percentuais de marketing).
- Validação final pelo schema **Pydantic** antes de persistir.

---

## Estrutura do Projeto

```
projeto-4/
├── main.py             # Entry point da API (uvicorn)
├── pipeline.py         # Orquestrador do pipeline completo
├── scheduler.py        # Agendador CronJob (polling)
├── requirements.txt
├── .env.example
├── .gitignore
└── src/
    ├── config.py       # Configurações centralizadas
    ├── models/
    │   └── schemas.py  # Contrato Semântico (Pydantic)
    ├── extraction/
    │   ├── scraper.py  # Web scraping dos portais RI
    │   ├── pdf_parser.py # Parsing e chunking semântico
    │   └── catalog.py  # Catálogo + linhagem (SHA-256)
    ├── processing/
    │   └── llm_extractor.py # Motor LLM (GPT-4o-mini)
    ├── database/
    │   └── repository.py    # Persistência SQLite
    └── api/
        └── routes.py   # Endpoints FastAPI
```

---

## Como Executar

### 1. Pré-requisitos

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configurar API Key

```bash
cp .env.example .env
# Edite o .env e insira sua OPENAI_API_KEY
```

### 3. Executar o Pipeline (uma vez)

```bash
python scheduler.py --once
```

### 4. Executar o Scheduler (contínuo)

```bash
python scheduler.py
```

### 5. Iniciar a API

```bash
uvicorn main:app --reload --port 8000
```

Acesse a documentação interativa: **http://localhost:8000/docs**

---

## Endpoints da API

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/conjuntura` | Dados com filtros opcionais |
| `GET` | `/api/conjuntura?empresa=MRV&ano=2025&trimestre=3` | Filtrado por empresa/período |
| `GET` | `/api/conjuntura/empresas` | Lista empresas disponíveis |
| `GET` | `/api/conjuntura/historico/{empresa}` | Histórico completo de uma empresa |
| `GET` | `/api/catalogo` | Catálogo de PDFs processados (lineage) |
| `POST` | `/api/pipeline/run` | Dispara pipeline manualmente |

### Exemplo de Resposta

```json
GET /api/conjuntura?empresa=MRV&ano=2025&trimestre=3

{
  "total": 1,
  "filtros": {"empresa": "MRV", "ano": 2025, "trimestre": 3},
  "dados": [
    {
      "id": 1,
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
      "source_hash": "a3f8c2d1...",
      "coletado_em": "2025-11-15T12:00:00"
    }
  ]
}
```

---

## Schema do Banco de Dados

```sql
CREATE TABLE dados_operacionais (
    id                                   INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa                              TEXT    NOT NULL,
    ano                                  INTEGER NOT NULL,
    trimestre                            INTEGER NOT NULL,
    vendas_contratadas_unidades          INTEGER,
    vendas_contratadas_valor_milhoes_brl REAL,
    lancamentos_unidades                 INTEGER,
    lancamentos_valor_milhoes_brl        REAL,
    entregas_unidades                    INTEGER,
    estoque_unidades                     INTEGER,
    vsv_percentual                       REAL,
    receita_liquida_milhoes_brl          REAL,
    source_url                           TEXT NOT NULL,  -- Data Lineage
    source_hash                          TEXT NOT NULL,  -- Idempotência
    coletado_em                          TEXT NOT NULL,
    UNIQUE(empresa, ano, trimestre)
);
```

---

## Dependências Principais

| Lib | Versão | Finalidade |
|---|---|---|
| `fastapi` | 0.115.5 | API REST |
| `uvicorn` | 0.32.1 | Servidor ASGI |
| `openai` | 1.57.4 | LLM (GPT-4o-mini) |
| `pymupdf` | 1.25.1 | Parsing de PDF |
| `beautifulsoup4` | 4.12.3 | Web scraping |
| `pydantic` | 2.10.3 | Contrato Semântico |
| `schedule` | 1.2.2 | Agendamento CronJob |
| `python-dotenv` | 1.0.1 | Variáveis de ambiente |
