"""WSGI entry point: `uv run flask --app wsgi run`."""

from agent_backend.app import create_app

app = create_app()
