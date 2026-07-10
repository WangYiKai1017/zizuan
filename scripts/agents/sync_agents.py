#!/usr/bin/env python
"""Generate Codex agent adapters from the shared Markdown definitions."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / ".ai" / "agents"


def read_agent(path: Path) -> tuple[str, str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.DOTALL)
    if not match:
        raise ValueError(f"missing YAML frontmatter: {path}")

    frontmatter, prompt = match.groups()
    fields: dict[str, str] = {}
    for line in frontmatter.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()

    name = fields.get("name")
    description = fields.get("description")
    if not name or not description:
        raise ValueError(f"name and description are required: {path}")
    return name, description, prompt.strip() + "\n"


def main() -> None:
    for source in sorted(SOURCE_DIR.glob("*.md")):
        if source.name == "README.md":
            continue
        name, description, prompt = read_agent(source)
        adapter = SOURCE_DIR / f"{name}.toml"
        adapter.write_text(
            "\n".join(
                [
                    f"name = {json.dumps(name, ensure_ascii=False)}",
                    f"description = {json.dumps(description, ensure_ascii=False)}",
                    f"developer_instructions = {json.dumps(prompt, ensure_ascii=False)}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        print(adapter.relative_to(ROOT))


if __name__ == "__main__":
    main()
