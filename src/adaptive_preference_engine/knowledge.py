"""KnowledgeEntry model — factual knowledge stored in APE's knowledge table."""

from dataclasses import dataclass, field, fields as dc_fields
from typing import List, Optional
from datetime import datetime


def _filter_fields(cls, data: dict) -> dict:
    """Return only keys that are declared fields on the dataclass cls."""
    known = {f.name for f in dc_fields(cls)}
    return {k: v for k, v in data.items() if k in known}


@dataclass
class KnowledgeEntry:
    """Factual knowledge entry (project context, conventions, decisions, workflows)."""
    id: str
    partition: str
    category: str
    title: str
    tags: List[str]
    content: str

    confidence: float = 1.0
    source: str = "explicit"
    machine_origin: Optional[str] = None
    decay_exempt: bool = False
    access_count: int = 0
    token_estimate: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_used: str = field(default_factory=lambda: datetime.now().isoformat())
    archived: bool = False

    def to_dict(self):
        return {
            "id": self.id,
            "partition": self.partition,
            "category": self.category,
            "title": self.title,
            "tags": self.tags,
            "content": self.content,
            "confidence": self.confidence,
            "source": self.source,
            "machine_origin": self.machine_origin,
            "decay_exempt": self.decay_exempt,
            "access_count": self.access_count,
            "token_estimate": self.token_estimate,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "archived": self.archived,
        }

    @staticmethod
    def from_dict(data):
        data = dict(data)
        return KnowledgeEntry(**_filter_fields(KnowledgeEntry, data))
