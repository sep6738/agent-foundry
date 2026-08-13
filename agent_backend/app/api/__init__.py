"""API blueprints."""

from flask import Flask

from agent_backend.app.api.blueprints.health import health_bp
from agent_backend.app.api.blueprints.instructions import instructions_bp
from agent_backend.app.api.blueprints.memories import memories_bp
from agent_backend.app.api.blueprints.messages import messages_bp
from agent_backend.app.api.blueprints.projects import projects_bp
from agent_backend.app.api.blueprints.sessions import sessions_bp
from agent_backend.app.api.blueprints.skills import skills_bp
from agent_backend.app.api.blueprints.tools import tools_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(health_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(instructions_bp)
    app.register_blueprint(memories_bp)
    app.register_blueprint(skills_bp)
    app.register_blueprint(tools_bp)
