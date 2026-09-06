"""Planted: non-literal model, long inline template, delimited user text."""
from openai import OpenAI

client = OpenAI()
MODEL = "gpt-4o-2024-08-06"

def classify(text):
    return client.chat.completions.create(
        model=MODEL,
        max_tokens=50,
        messages=[{"role": "system", "content": "You classify."},
                  {"role": "user", "content": f"You are a careful classifier. You are a careful classifier. You are a careful classifier. You are a careful classifier. You are a careful classifier. You are a careful classifier. You are a careful classifier. You are a careful classifier. You are a careful classifier. You are a careful classifier. You are a careful classifier. You are a careful classifier. You are a careful classifier. You are a careful classifier. <document>\n{text}\n</document>"}],
    )
