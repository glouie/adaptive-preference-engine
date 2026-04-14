"""Generate Claude Code memory .md files from APE knowledge entries."""

import os
import re
import tempfile
from pathlib import Path
from typing import Optional, Dict, List

# Category -> memory type mapping
CATEGORY_TO_TYPE = {
    "preference": "feedback",
    "convention": "feedback",
    "pattern": "feedback",
    "decision": "project",
    "context": "project",
    "reference": "reference",
}

# Memory type -> APE category/partition mapping
TYPE_TO_CATEGORY = {
    "feedback": "preference",
    "user": "context",
    "project": "context",
    "reference": "reference",
}


def generate_memory_files(
    public_mgr,
    confidential_mgr,
    memory_dir: Path,
) -> int:
    """Generate .md files from knowledge entries into memory_dir.

    Returns count of files generated.
    """
    memory_dir = Path(memory_dir)
    memory_dir.mkdir(parents=True, exist_ok=True)

    entries = public_mgr.knowledge.get_all_entries(include_archived=False)
    if confidential_mgr:
        entries += confidential_mgr.knowledge.get_all_entries(include_archived=False)

    generated = 0
    index_lines = []

    for entry in entries:
        mem_type = CATEGORY_TO_TYPE.get(entry.category, "project")
        slug = re.sub(r'[^a-z0-9]+', '_', entry.title.lower()).strip('_')
        filename = f"{mem_type}_{slug}.md"

        content = (
            f"---\n"
            f"name: {entry.title}\n"
            f"description: {entry.content[:80]}\n"
            f"type: {mem_type}\n"
            f"---\n\n"
            f"{entry.content}\n"
        )

        # Atomic write: temp file + rename
        target = memory_dir / filename
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=f".{filename}.", suffix=".tmp", dir=str(memory_dir)
        )
        try:
            os.write(tmp_fd, content.encode("utf-8"))
            os.close(tmp_fd)
            os.rename(tmp_path, str(target))
        except Exception:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

        index_lines.append(f"- [{entry.title}]({filename}) -- {entry.content[:60]}")
        generated += 1

    # Generate MEMORY.md index
    index_content = "# Memory Index\n\n" + "\n".join(index_lines) + "\n"
    index_target = memory_dir / "MEMORY.md"
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".MEMORY.md.", suffix=".tmp", dir=str(memory_dir)
    )
    try:
        os.write(tmp_fd, index_content.encode("utf-8"))
        os.close(tmp_fd)
        os.rename(tmp_path, str(index_target))
    except Exception:
        try:
            os.close(tmp_fd)
        except OSError:
            pass
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return generated


def parse_memory_file(file_path: Path) -> Dict:
    """Parse a Claude Code memory .md file into APE knowledge fields.

    Returns dict with: name, description, type, category, partition, content.
    """
    text = Path(file_path).read_text()

    # Split frontmatter and body
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter_text = parts[1].strip()
            body = parts[2].strip()
        else:
            frontmatter_text = ""
            body = text
    else:
        frontmatter_text = ""
        body = text

    # Parse YAML frontmatter (simple key: value)
    fm = {}
    for line in frontmatter_text.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip()

    mem_type = fm.get("type", "project")
    category = TYPE_TO_CATEGORY.get(mem_type, "context")

    # Determine partition from type
    if mem_type == "user":
        partition = "user"
    elif mem_type == "project":
        partition = "projects/unknown"
    else:
        partition = "general"

    return {
        "name": fm.get("name", Path(file_path).stem),
        "description": fm.get("description", ""),
        "type": mem_type,
        "category": category,
        "partition": partition,
        "content": body,
    }
