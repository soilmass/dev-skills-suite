"""Application service — allowed to depend on the domain layer."""
import src.domain.order


class OrderService:
    def place(self):
        return src.domain.order.Order()
