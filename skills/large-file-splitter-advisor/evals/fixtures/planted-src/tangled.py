"""Planted fixture: an oversized module whose definitions all reference
one another, so there is no mechanical seam."""


class Engine:
    def __init__(self):
        self.parts = []

    def run(self):
        return [step(self, p) for p in self.parts]


def step(engine, part):
    return finish(engine, part)


def finish(engine, part):
    return (engine, part)


def build():
    e = Engine()
    e.parts.append("a")
    return e


def main():
    return build().run()


def helper_one():
    return main()


def helper_two():
    return helper_one()


def helper_three():
    return helper_two()


def helper_four():
    return helper_three()


def helper_five():
    return helper_four()


def helper_six():
    return helper_five()
