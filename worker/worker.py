import logging
import time

from core.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("PyQueue Worker starting up...")
    logger.info(f"Worker concurrency: {settings.worker_concurrency}")
    # Phase 4: real task polling loop goes here
    while True:
        logger.info("Worker heartbeat — waiting for tasks...")
        time.sleep(5)


if __name__ == "__main__":
    main()

