"""HTTP adapter — allowed to depend on the application layer."""
import src.application.service


def handle_place_order():
    return src.application.service.OrderService().place()
