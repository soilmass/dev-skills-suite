"""Planted fixture: a third spelling of the user attribute."""
import logging

log = logging.getLogger(__name__)


def resume(uid, order_id):
    log.info("session resumed", uid=uid)  # planted: uid variant
    log.info("cart updated", order_id=order_id)
