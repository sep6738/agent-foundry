"""Render instruction bundles into bounded system-prompt text."""

from __future__ import annotations

from agent_backend.app.instructions.loader import InstructionBundle


class PromptInjector:
    @staticmethod
    def inject(bundle: InstructionBundle, budget_tokens: int) -> str:
        if not bundle.files:
            return ""
        budget_chars = budget_tokens * 4
        parts: list[str] = []
        used = 0
        for file in sorted(bundle.files, key=lambda item: item.priority, reverse=True):
            full = [f'<project_instructions path="{file.path}">']
            for name, body in file.sections.items():
                full.append(f'<section name="{name}">\n{body.strip()}\n</section>')
            full.append("</project_instructions>")
            full_text = "\n".join(full)
            if used + len(full_text) <= budget_chars:
                parts.append(full_text)
                used += len(full_text) + 2
                if used >= budget_chars:
                    break
                continue
            partial = [f'<project_instructions path="{file.path}">']
            for name, body in file.sections.items():
                section = f'<section name="{name}">\n{body.strip()}\n</section>'
                if used + len(section) + 2 > budget_chars:
                    continue
                partial.append(section)
                used += len(section) + 2
            partial.append("</project_instructions>")
            if len(partial) > 2:
                parts.append("\n".join(partial))
            break
        return "\n".join(parts)
