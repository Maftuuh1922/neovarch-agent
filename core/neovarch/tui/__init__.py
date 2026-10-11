"""Terminal UI for `neovarch` (interactive chat, splash and branding)."""


def available() -> bool:
    """True when the TUI's libraries (rich, prompt_toolkit) can be imported."""
    try:
        import prompt_toolkit  # noqa: F401
        import rich  # noqa: F401
    except ImportError:
        return False
    return True
