"""
DevMesh Task Templates Service
------------------------------
Template-based task creation with variable substitution and validation.
"""

from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field
from datetime import datetime
import re
import logging

log = logging.getLogger("devmesh.templates")


__all__ = [
    "TaskTemplate",
    "TemplateManager",
    "get_template_manager",
]


@dataclass
class TaskTemplate:
    """A task template with variable substitution."""

    template_id: str
    name: str
    description: str
    description_template: str  # Template with {variables}
    working_dir_template: str = "/tmp"
    file_template: str = ""
    operation: str = "create"
    priority: int = 1
    required_capabilities: List[str] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)  # Variable: default value
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def render(self, bindings: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Render template with variable bindings."""
        bindings = bindings or {}

        # Validate required variables
        for var_name, var_info in self.variables.items():
            if isinstance(var_info, dict) and var_info.get("required", False):
                if var_name not in bindings:
                    raise ValueError(f"Required variable not provided: {var_name}")

        # Substitute variables
        context = {
            var_name: bindings.get(var_name, var_info if isinstance(var_info, str) else "")
            for var_name, var_info in self.variables.items()
        }
        context.update(bindings)  # Override with provided bindings

        return {
            "description": self.description_template.format(**context),
            "working_dir": self.working_dir_template.format(**context),
            "file": self.file_template.format(**context),
            "operation": self.operation,
            "priority": self.priority,
            "required_capabilities": self.required_capabilities,
        }


class TemplateManager:
    """Manages task templates."""

    def __init__(self):
        self.templates: Dict[str, TaskTemplate] = {}
        self._built_in_templates = self._create_built_in_templates()
        # Load built-in templates
        for template in self._built_in_templates:
            self.templates[template.template_id] = template

    def _create_built_in_templates(self) -> List[TaskTemplate]:
        """Create built-in templates for common tasks."""
        return [
            TaskTemplate(
                template_id="simple_analysis",
                name="Simple Analysis",
                description="Analyze a file or directory",
                description_template="Analyze {target} and produce a summary",
                file_template="{target}",
                operation="analyze",
                variables={
                    "target": {"required": True, "description": "File or directory to analyze"},
                },
            ),
            TaskTemplate(
                template_id="code_review",
                name="Code Review",
                description="Review code for quality and issues",
                description_template="Review the code in {path} for bugs, style issues, and improvements",
                file_template="{path}",
                operation="review",
                variables={
                    "path": {"required": True, "description": "Code file to review"},
                    "focus": {
                        "description": "Specific focus area (e.g., 'security', 'performance')"
                    },
                },
            ),
            TaskTemplate(
                template_id="refactor",
                name="Refactor Code",
                description="Refactor code for improved quality",
                description_template="Refactor {file_path} to improve {aspect}",
                file_template="{file_path}",
                operation="refactor",
                variables={
                    "file_path": {"required": True, "description": "File to refactor"},
                    "aspect": {"description": "What to improve"},
                },
            ),
            TaskTemplate(
                template_id="documentation",
                name="Write Documentation",
                description="Generate documentation for code",
                description_template="Generate documentation for {target_file}",
                file_template="{target_file}",
                operation="document",
                variables={
                    "target_file": {"required": True, "description": "File to document"},
                    "style": {"description": "Documentation style (e.g., 'markdown', 'html')"},
                },
            ),
            TaskTemplate(
                template_id="testing",
                name="Generate Tests",
                description="Generate test cases",
                description_template="Generate test cases for {source_file}",
                file_template="{source_file}",
                operation="test",
                variables={
                    "source_file": {"required": True, "description": "Source file to test"},
                    "test_type": {"description": "Type of tests (e.g., 'unit', 'integration')"},
                },
            ),
        ]

    def register_template(self, template: TaskTemplate) -> None:
        """Register a custom template."""
        self.templates[template.template_id] = template
        log.info(f"Template registered: {template.template_id}")

    def unregister_template(self, template_id: str) -> bool:
        """Unregister a template (custom only, not built-in)."""
        if template_id.startswith("_"):  # Don't allow unregistering built-in
            return False

        if template_id in self.templates:
            del self.templates[template_id]
            log.info(f"Template unregistered: {template_id}")
            return True
        return False

    def get_template(self, template_id: str) -> Optional[TaskTemplate]:
        """Get a template by ID."""
        return self.templates.get(template_id)

    def list_templates(self) -> List[TaskTemplate]:
        """List all templates."""
        return list(self.templates.values())

    def create_task_from_template(
        self,
        template_id: str,
        bindings: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Create a task from a template."""
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")

        task_dict = template.render(bindings)
        return task_dict

    def export_template(self, template_id: str) -> Dict[str, Any]:
        """Export a template as a dictionary."""
        template = self.get_template(template_id)
        if not template:
            return {}

        return {
            "template_id": template.template_id,
            "name": template.name,
            "description": template.description,
            "description_template": template.description_template,
            "working_dir_template": template.working_dir_template,
            "file_template": template.file_template,
            "operation": template.operation,
            "priority": template.priority,
            "required_capabilities": template.required_capabilities,
            "variables": template.variables,
        }


# Global template manager instance
_template_manager: Optional[TemplateManager] = None


def get_template_manager() -> TemplateManager:
    """Get the global template manager instance."""
    global _template_manager
    if _template_manager is None:
        _template_manager = TemplateManager()
    return _template_manager
