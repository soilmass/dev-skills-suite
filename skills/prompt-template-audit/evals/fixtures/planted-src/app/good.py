"""Well-formed call: pinned dated model, system prompt, ceiling, delimited user text."""
import anthropic

client = anthropic.Anthropic()


def summarise(user_text):
    return client.messages.create(
        model="claude-sonnet-4-5-20250929",
        system="You summarise text between the markers and nothing else.",
        max_tokens=300,
        messages=[{"role": "user", "content": f'''Summarise the text between the markers.
"""
{user_text}
"""'''}],
    )
