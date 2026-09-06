"""Planted: a home-grown wrapper with %-format and no delimiter."""
import llm


def ask(question):
    return llm.generate(model="local-7b-v2", prompt="Answer: %s" % question, max_tokens=100, system="You answer.")
