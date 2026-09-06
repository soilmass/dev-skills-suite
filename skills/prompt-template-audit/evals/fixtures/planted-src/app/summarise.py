"""Planted: alias model, undelimited f-string, no max_tokens, no system."""
import anthropic

client = anthropic.Anthropic()

def summarise(user_text):
    return client.messages.create(
        model="claude-latest",
        messages=[{"role": "user", "content": f"Summarise: {user_text}"}],
    )
