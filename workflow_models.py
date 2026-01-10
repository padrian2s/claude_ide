"""Data models for workflow chain system."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from pathlib import Path
import uuid
from datetime import datetime


class NodeStatus(Enum):
    """Status of a workflow node."""
    PENDING = "pending"      # Waiting in queue
    RUNNING = "running"      # Currently executing
    COMPLETED = "completed"  # Successfully finished
    FAILED = "failed"        # Execution failed
    SKIPPED = "skipped"      # User skipped this node
    PAUSED = "paused"        # Execution paused


@dataclass
class WorkflowNode:
    """Single node in workflow chain."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    project_path: str = ""              # Favorite folder path
    prompt_template: str = ""           # Prompt to execute
    context_files: list[str] = field(default_factory=list)  # Files to include
    status: NodeStatus = NodeStatus.PENDING
    output: str = ""                    # Captured output
    tmux_pane: Optional[str] = None     # tmux pane ID when running
    depends_on: list[str] = field(default_factory=list)  # Node IDs
    started_at: Optional[str] = None    # ISO timestamp
    completed_at: Optional[str] = None  # ISO timestamp
    error_message: str = ""             # Error if failed

    @property
    def project_name(self) -> str:
        """Get project folder name."""
        return Path(self.project_path).name if self.project_path else ""

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate duration if started."""
        if not self.started_at:
            return None
        start = datetime.fromisoformat(self.started_at)
        if self.completed_at:
            end = datetime.fromisoformat(self.completed_at)
        else:
            end = datetime.now()
        return (end - start).total_seconds()

    @property
    def duration_str(self) -> str:
        """Human-readable duration."""
        secs = self.duration_seconds
        if secs is None:
            return ""
        mins, secs = divmod(int(secs), 60)
        if mins > 0:
            return f"{mins}m {secs}s"
        return f"{secs}s"

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "project_path": self.project_path,
            "prompt_template": self.prompt_template,
            "context_files": self.context_files,
            "status": self.status.value,
            "output": self.output,
            "tmux_pane": self.tmux_pane,
            "depends_on": self.depends_on,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowNode":
        """Deserialize from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            project_path=data.get("project_path", ""),
            prompt_template=data.get("prompt_template", ""),
            context_files=data.get("context_files", []),
            status=NodeStatus(data.get("status", "pending")),
            output=data.get("output", ""),
            tmux_pane=data.get("tmux_pane"),
            depends_on=data.get("depends_on", []),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error_message=data.get("error_message", ""),
        )


@dataclass
class WorkflowChain:
    """Complete workflow chain definition."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    nodes: list[WorkflowNode] = field(default_factory=list)
    global_context: str = ""            # Shared context for all nodes
    propagate_output: bool = True       # Pass output to next node
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def get_runnable_nodes(self) -> list[WorkflowNode]:
        """Get nodes ready to run (dependencies satisfied)."""
        completed_ids = {n.id for n in self.nodes if n.status == NodeStatus.COMPLETED}
        return [
            n for n in self.nodes
            if n.status == NodeStatus.PENDING
            and all(dep in completed_ids for dep in n.depends_on)
        ]

    def get_running_nodes(self) -> list[WorkflowNode]:
        """Get currently running nodes."""
        return [n for n in self.nodes if n.status == NodeStatus.RUNNING]

    def get_pending_nodes(self) -> list[WorkflowNode]:
        """Get pending nodes."""
        return [n for n in self.nodes if n.status == NodeStatus.PENDING]

    def get_completed_nodes(self) -> list[WorkflowNode]:
        """Get completed nodes."""
        return [n for n in self.nodes if n.status == NodeStatus.COMPLETED]

    def is_complete(self) -> bool:
        """Check if all nodes are done."""
        return all(
            n.status in (NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.SKIPPED)
            for n in self.nodes
        )

    def has_failed(self) -> bool:
        """Check if any node failed."""
        return any(n.status == NodeStatus.FAILED for n in self.nodes)

    def reset(self):
        """Reset all nodes to pending."""
        for node in self.nodes:
            node.status = NodeStatus.PENDING
            node.output = ""
            node.tmux_pane = None
            node.started_at = None
            node.completed_at = None
            node.error_message = ""

    def add_node(self, project_path: str, prompt: str = "",
                 context_files: list[str] = None, depends_on: list[str] = None) -> WorkflowNode:
        """Add a new node to the chain."""
        node = WorkflowNode(
            project_path=project_path,
            prompt_template=prompt,
            context_files=context_files or [],
            depends_on=depends_on or [],
        )
        self.nodes.append(node)
        self.updated_at = datetime.now().isoformat()
        return node

    def remove_node(self, node_id: str):
        """Remove a node and update dependencies."""
        self.nodes = [n for n in self.nodes if n.id != node_id]
        # Remove from dependencies
        for node in self.nodes:
            node.depends_on = [d for d in node.depends_on if d != node_id]
        self.updated_at = datetime.now().isoformat()

    def move_node(self, node_id: str, new_index: int):
        """Move a node to a new position."""
        node = next((n for n in self.nodes if n.id == node_id), None)
        if node:
            self.nodes.remove(node)
            self.nodes.insert(new_index, node)
            self.updated_at = datetime.now().isoformat()

    def get_node_by_id(self, node_id: str) -> Optional[WorkflowNode]:
        """Get node by ID."""
        return next((n for n in self.nodes if n.id == node_id), None)

    @property
    def progress(self) -> tuple[int, int]:
        """Return (completed, total) node counts."""
        completed = len([n for n in self.nodes if n.status in
                        (NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.SKIPPED)])
        return completed, len(self.nodes)

    @property
    def progress_percent(self) -> float:
        """Return progress as percentage."""
        completed, total = self.progress
        return (completed / total * 100) if total > 0 else 0

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "nodes": [n.to_dict() for n in self.nodes],
            "global_context": self.global_context,
            "propagate_output": self.propagate_output,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowChain":
        """Deserialize from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            name=data.get("name", ""),
            nodes=[WorkflowNode.from_dict(n) for n in data.get("nodes", [])],
            global_context=data.get("global_context", ""),
            propagate_output=data.get("propagate_output", True),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )


# Status display helpers
STATUS_ICONS = {
    NodeStatus.PENDING: "⏳",
    NodeStatus.RUNNING: "🔄",
    NodeStatus.COMPLETED: "✅",
    NodeStatus.FAILED: "❌",
    NodeStatus.SKIPPED: "⏭️",
    NodeStatus.PAUSED: "⏸️",
}

STATUS_COLORS = {
    NodeStatus.PENDING: "dim",
    NodeStatus.RUNNING: "cyan",
    NodeStatus.COMPLETED: "green",
    NodeStatus.FAILED: "red",
    NodeStatus.SKIPPED: "yellow",
    NodeStatus.PAUSED: "yellow",
}
