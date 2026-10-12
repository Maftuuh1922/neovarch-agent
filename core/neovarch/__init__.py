"""Neovarch Agent core.

An original agent runtime for the Neovarch desktop and phone apps: an
OpenAI-compatible chat loop with tool calling, sessions/memory/skills under
``~/.neovarch``, and ``neovarch serve`` — an HTTP + WebSocket gateway whose wire
format is compatible with what the Neovarch desktop and the Neovarch phone
remote speak. Third-party attribution is in the repository NOTICE file.
"""

__version__ = "1.4.7"
PRODUCT = "Neovarch Agent"
