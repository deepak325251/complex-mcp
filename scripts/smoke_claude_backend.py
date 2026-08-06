import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.agent import ClaudeCodeBackend


async def main():
    backend = ClaudeCodeBackend(model="claude-sonnet-4-5")
    messages = [
        {"role": "system", "content": "You reply with exactly one word."},
        {"role": "user", "content": "Reply with only the single word PING."},
    ]
    resp = await backend.chat(messages, max_tokens=32)

    content = resp.choices[0].message.content
    usage = resp.usage
    print(f"content={content!r}")
    print(f"usage=prompt:{usage.prompt_tokens} completion:{usage.completion_tokens} total:{usage.total_tokens}")
    print(f"finish_reason={resp.choices[0].finish_reason}")

    assert content, "empty content"
    assert "PING" in content.upper(), f"expected PING in reply, got: {content!r}"
    print("SMOKE PASS")


if __name__ == "__main__":
    asyncio.run(main())
