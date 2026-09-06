"""Domain entity — should depend on nothing outside the domain layer."""
import src.infrastructure.db


class Order:
    def save(self):
        return src.infrastructure.db.write(self)
