"""No LLM calls here."""


def save(db, name):
    return db.create(name=name)
