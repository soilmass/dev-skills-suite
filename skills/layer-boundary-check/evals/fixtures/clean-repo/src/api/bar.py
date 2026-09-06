"""API module — allowed to depend inward on core."""
import src.core.foo


def bar():
    return src.core.foo.foo()
