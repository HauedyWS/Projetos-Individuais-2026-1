"""
scheduler.py - Agendador do Pipeline (CronJob / Polling).

Estratégia de gatilho: Polling por Agendamento.
  - O pipeline é executado periodicamente (padrão: a cada 24 horas).
  - Isso evita sobrecarga nos servidores das empresas (sem flood de requests).
  - O intervalo é configurável via variável SCRAPING_INTERVAL_HOURS no .env.

Uso:
  python scheduler.py          → inicia o scheduler (roda indefinidamente)
  python scheduler.py --once   → executa o pipeline uma vez e encerra

O scheduler pode ser mantido rodando em background com:
  nohup python scheduler.py &   (Linux/Mac)
  start pythonw scheduler.py    (Windows, sem janela)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import schedule

from src.config import SCRAPING_INTERVAL_HOURS
from pipeline import run_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def job():
    """Tarefa agendada: executa o pipeline e registra o resultado."""
    logger.info("⏰ Ciclo de coleta iniciado pelo scheduler.")
    try:
        stats = run_pipeline()
        logger.info(
            "⏰ Ciclo concluído. Novos registros: %d | Erros: %d",
            stats["registros_salvos"],
            stats["erros"],
        )
    except Exception as exc:
        logger.error("❌ Erro no ciclo do scheduler: %s", exc, exc_info=True)


def main():
    parser = argparse.ArgumentParser(
        description="Scheduler do Pipeline UDA — Conjuntura Habitacional"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Executa o pipeline uma única vez e encerra.",
    )
    args = parser.parse_args()

    if args.once:
        logger.info("▶️  Executando pipeline uma única vez (--once).")
        job()
        return

    logger.info(
        "🕐 Scheduler iniciado. Pipeline executará a cada %d hora(s).",
        SCRAPING_INTERVAL_HOURS,
    )

    # Agenda a tarefa
    schedule.every(SCRAPING_INTERVAL_HOURS).hours.do(job)

    # Executa imediatamente na primeira vez
    logger.info("▶️  Executando pipeline imediatamente (primeira execução).")
    job()

    # Loop do scheduler
    while True:
        schedule.run_pending()
        time.sleep(60)  # Verifica a cada 1 minuto


if __name__ == "__main__":
    main()
