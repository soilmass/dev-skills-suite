"""Planted fixture: one logging call per drift pattern, eleven calls in all with sessions.py."""
import logging

logger = logging.getLogger(__name__)


def price(order_id, user_id, duration_ms):
    logger.info("order priced", order_id=order_id, user_id=user_id, duration_ms=duration_ms)
    logger.info("payment failed for order", order_id=order_id, user_id=user_id)  # planted: failure at info
    logger.error("worker started", worker="pricing-1")  # planted: normal operation at error
    logger.warning("login attempt", userId=user_id, password="hunter2")  # planted: variant spelling + secret
    logger.info(f"pricing order {order_id}")  # planted: f-string message
    logger.debug("retry %s" % 3)  # planted: percent-format message


def charge(order_id):
    try:
        raise RuntimeError("gateway")
    except RuntimeError:
        logger.error("gateway call failed", order_id=order_id)  # planted: no traceback
    try:
        raise RuntimeError("gateway")
    except RuntimeError:
        logger.exception("gateway call raised")  # fine: .exception carries the traceback
    try:
        raise RuntimeError("gateway")
    except RuntimeError:
        logger.error("charge failed", exc_info=True)  # fine: exc_info
