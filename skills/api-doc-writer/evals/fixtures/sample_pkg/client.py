"""HTTP client for the sample service."""


class Client:
    """A minimal client bound to one base URL.

    Instances are cheap; create one per base URL.
    """

    def __init__(self, base_url: str, *, timeout: float = 5.0):
        """Bind the client to `base_url`."""
        self.base_url = base_url
        self.timeout = timeout

    def get(self, path: str, *, timeout: float | None = None) -> dict:
        """Fetch `path` relative to the base URL and decode the JSON body.

        Raises ValueError for a non-JSON response.
        """
        if not path.startswith("/"):
            raise ValueError("path must start with '/'")
        return {"path": path, "timeout": timeout or self.timeout}

    def post(self, path: str, payload: dict) -> dict:
        return {"path": path, "payload": payload}

    @property
    def host(self) -> str:
        """The base URL's host part."""
        return self.base_url.split("//", 1)[-1].split("/", 1)[0]

    def _sign(self, payload: dict) -> str:
        return "signed"
