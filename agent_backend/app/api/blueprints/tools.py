"""Tool listing endpoint."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

tools_bp = Blueprint("tools", __name__, url_prefix="/v1/tools")


@tools_bp.get("")
def list_tools():
    runtime_context = current_app.extensions["runtime_context"]
    tools = runtime_context.tool_registry.list()
    return jsonify(
        {
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                    "permissions": sorted(tool.permissions),
                }
                for tool in tools
            ]
        }
    )
