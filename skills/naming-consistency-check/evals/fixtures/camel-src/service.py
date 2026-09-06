"""Planted fixture: a tree that consistently uses camelCase functions and
arguments. The check reports what deviates from the tree, not from PEP 8,
so this module must draw no mixed-convention finding."""

MAX_ITEMS = 10
PAGE_SIZE = 20
API_VERSION = "v2"


class OrderService:
    def listOrders(self, customerId, pageSize=PAGE_SIZE):
        return [customerId] * pageSize

    def cancelOrder(self, orderId):
        return orderId


def buildClient(baseUrl, apiVersion=API_VERSION):
    return (baseUrl, apiVersion)


def parseResponse(rawBody):
    return rawBody
