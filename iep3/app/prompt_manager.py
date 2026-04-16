"""Prompt version manager for IEP3.

Prompts are stored as versioned text files in iep3/prompts/.
Rules:
- Never edit a prompt file in place — create a new version (v2_report.txt, etc.)
- The active version is controlled by the PROMPT_VERSION env var (default: v1).
- Document any version change in docs/tradeoffs.md.
"""

import os

# Prompts directory is two levels up from this file (iep3/prompts/)
_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def load_prompt(version: str | None = None) -> str:
    """Load the prompt text for the given version.

    Args:
        version: Prompt version string, e.g. "v1".  If None, falls back to
                 the PROMPT_VERSION environment variable, then to "v1".

    Returns:
        The raw prompt text as a string.

    Raises:
        FileNotFoundError: If the prompt file for the requested version does
                           not exist in the prompts directory.
    """
    if version is None:
        version = os.getenv("PROMPT_VERSION", "v1")

    filename = f"{version}_report.txt"
    path = os.path.join(_PROMPTS_DIR, filename)

    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Prompt file not found: {path!r}.  "
            f"Available versions: {list_versions()}"
        )

    with open(path, encoding="utf-8") as fh:
        return fh.read()


def list_versions() -> list[str]:
    """Return a sorted list of available prompt version names.

    Returns:
        List of version strings, e.g. ["v1", "v2"].
    """
    try:
        files = os.listdir(_PROMPTS_DIR)
    except FileNotFoundError:
        return []
    versions = [
        f.replace("_report.txt", "")
        for f in sorted(files)
        if f.endswith("_report.txt")
    ]
    return versions
