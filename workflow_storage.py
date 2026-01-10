"""Storage and persistence for workflow chains."""

import json
from pathlib import Path
from typing import Optional
from datetime import datetime

from workflow_models import WorkflowChain, WorkflowNode

# Storage file path (same directory as script)
SCRIPT_DIR = Path(__file__).parent
WORKFLOWS_FILE = SCRIPT_DIR / ".tui_workflows.json"
DEPS_FILE = SCRIPT_DIR / ".tui_dependencies.json"


def _load_storage() -> dict:
    """Load storage file."""
    if WORKFLOWS_FILE.exists():
        try:
            with open(WORKFLOWS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "workflows": {},
        "active_workflow": None,
        "execution_history": [],
    }


def _save_storage(data: dict):
    """Save storage file."""
    with open(WORKFLOWS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_workflows() -> dict[str, WorkflowChain]:
    """Load all workflows."""
    data = _load_storage()
    workflows = {}
    for wf_id, wf_data in data.get("workflows", {}).items():
        workflows[wf_id] = WorkflowChain.from_dict(wf_data)
    return workflows


def save_workflow(workflow: WorkflowChain):
    """Save a single workflow."""
    data = _load_storage()
    workflow.updated_at = datetime.now().isoformat()
    data["workflows"][workflow.id] = workflow.to_dict()
    _save_storage(data)


def delete_workflow(workflow_id: str):
    """Delete a workflow."""
    data = _load_storage()
    if workflow_id in data.get("workflows", {}):
        del data["workflows"][workflow_id]
        _save_storage(data)


def get_workflow(workflow_id: str) -> Optional[WorkflowChain]:
    """Get a specific workflow."""
    workflows = load_workflows()
    return workflows.get(workflow_id)


def get_active_workflow_id() -> Optional[str]:
    """Get the currently active/running workflow ID."""
    data = _load_storage()
    return data.get("active_workflow")


def set_active_workflow(workflow_id: Optional[str]):
    """Set the active workflow."""
    data = _load_storage()
    data["active_workflow"] = workflow_id
    _save_storage(data)


def add_execution_history(workflow_id: str, status: str, duration: float = 0):
    """Add execution record to history."""
    data = _load_storage()
    if "execution_history" not in data:
        data["execution_history"] = []

    data["execution_history"].append({
        "workflow_id": workflow_id,
        "status": status,
        "duration": duration,
        "timestamp": datetime.now().isoformat(),
    })

    # Keep last 50 entries
    data["execution_history"] = data["execution_history"][-50:]
    _save_storage(data)


def get_execution_history(limit: int = 20) -> list[dict]:
    """Get recent execution history."""
    data = _load_storage()
    history = data.get("execution_history", [])
    return list(reversed(history[-limit:]))


def migrate_from_dependencies():
    """Migrate existing dependency chains to workflow format."""
    if not DEPS_FILE.exists():
        return

    try:
        with open(DEPS_FILE) as f:
            deps_data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return

    data = _load_storage()
    migrated = 0

    for project_path, dep_info in deps_data.items():
        # Skip if not a dependency definition
        if not isinstance(dep_info, (dict, list)):
            continue

        # Handle old format (list) and new format (dict)
        if isinstance(dep_info, list):
            chain = dep_info
            instructions = ""
        else:
            chain = dep_info.get("chain", [])
            instructions = dep_info.get("instructions", "")

        if not chain:
            continue

        # Create workflow from dependency chain
        project_name = Path(project_path).name
        workflow = WorkflowChain(
            name=f"{project_name} Chain",
            global_context=instructions,
        )

        # Add each dependency as a node
        prev_node_id = None
        for dep_path in chain:
            node = workflow.add_node(
                project_path=dep_path,
                depends_on=[prev_node_id] if prev_node_id else [],
            )
            prev_node_id = node.id

        # Store with project path as key for reference
        data["workflows"][workflow.id] = workflow.to_dict()
        migrated += 1

    if migrated > 0:
        _save_storage(data)

    return migrated


def export_workflow(workflow_id: str, export_path: Path) -> bool:
    """Export a workflow to a file."""
    workflow = get_workflow(workflow_id)
    if not workflow:
        return False

    with open(export_path, "w") as f:
        json.dump(workflow.to_dict(), f, indent=2)
    return True


def import_workflow(import_path: Path) -> Optional[WorkflowChain]:
    """Import a workflow from a file."""
    if not import_path.exists():
        return None

    try:
        with open(import_path) as f:
            data = json.load(f)
        workflow = WorkflowChain.from_dict(data)
        # Generate new ID to avoid conflicts
        workflow.id = str(__import__("uuid").uuid4())[:8]
        save_workflow(workflow)
        return workflow
    except (json.JSONDecodeError, IOError):
        return None


def create_workflow(name: str, global_context: str = "",
                   propagate_output: bool = True) -> WorkflowChain:
    """Create and save a new workflow."""
    workflow = WorkflowChain(
        name=name,
        global_context=global_context,
        propagate_output=propagate_output,
    )
    save_workflow(workflow)
    return workflow


def duplicate_workflow(workflow_id: str, new_name: str = None) -> Optional[WorkflowChain]:
    """Duplicate an existing workflow."""
    original = get_workflow(workflow_id)
    if not original:
        return None

    # Create new workflow with copied data
    new_workflow = WorkflowChain(
        name=new_name or f"{original.name} (copy)",
        global_context=original.global_context,
        propagate_output=original.propagate_output,
    )

    # Copy nodes with new IDs
    id_mapping = {}  # old_id -> new_id
    for old_node in original.nodes:
        new_node = new_workflow.add_node(
            project_path=old_node.project_path,
            prompt=old_node.prompt_template,
            context_files=old_node.context_files.copy(),
        )
        id_mapping[old_node.id] = new_node.id

    # Update dependencies with new IDs
    for i, old_node in enumerate(original.nodes):
        new_workflow.nodes[i].depends_on = [
            id_mapping.get(dep, dep) for dep in old_node.depends_on
        ]

    save_workflow(new_workflow)
    return new_workflow
