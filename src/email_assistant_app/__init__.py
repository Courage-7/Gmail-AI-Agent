"""Email assistant application package."""

from __future__ import annotations


def main() -> None:
    """Run the local API server."""
    import uvicorn

    uvicorn.run("email_assistant_app.main:app", host="0.0.0.0", port=8000)
