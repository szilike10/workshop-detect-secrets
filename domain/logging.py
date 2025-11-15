import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
    force=True,  # overrides any earlier config (Jupyter, dotenv, etc.)
)
logger = logging.getLogger("workflow")