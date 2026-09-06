"""Planted fixture entry point: references helper and the plugin registry."""
from used import helper
from dynamic import REGISTRY


def main():
    print(helper(2))
    REGISTRY["plugin_hook"]()


if __name__ == "__main__":
    main()
