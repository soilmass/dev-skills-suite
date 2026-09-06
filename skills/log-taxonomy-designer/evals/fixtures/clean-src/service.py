"""Planted fixture: consistent, constant-template logging; must draw nothing."""
import logging

logger = logging.getLogger(__name__)


def handle(order_id, user_id):
    logger.info("request received", order_id=order_id, user_id=user_id)
    logger.info("order priced", order_id=order_id, user_id=user_id, duration_ms=12)
    try:
        raise ValueError("bad")
    except ValueError:
        logger.exception("pricing raised", order_id=order_id)
