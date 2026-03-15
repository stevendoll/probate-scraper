#!/usr/bin/env python3
"""
Claude Code Stop hook — extracts user prompts from the current session
and writes a readable markdown log to docs/sessions/.

Runs automatically at the end of every Claude session. Configure in
.claude/settings.json:
  { "hooks": { "Stop": [{ "hooks": [{ "type": "command",
      "command": "python3 scripts/extract_session.py" }] }] } }
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def main():
    payload = json.load(sys.stdin)

    # Don't block Claude from stopping — always exit 0
    # (stop_hook_active=true means Claude is already in a stop hook response loop)
    if payload.get("stop_hook_active"):
        sys.exit(0)

    transcript_path = payload.get("transcript_path", "")
    session_id = payload.get("session_id", "unknown")
    cwd = payload.get("cwd", os.getcwd())

    if not transcript_path or not Path(transcript_path).exists():
        sys.exit(0)

    # Parse the session JSONL
    entries = []
    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    # Extract user prompts
    prompts = []
    git_branch = None

    for entry in entries:
        # Grab git branch from any entry that has it
        if not git_branch and entry.get("gitBranch"):
            git_branch = entry["gitBranch"]

        if entry.get("type") != "user":
            continue

        content = entry.get("message", {}).get("content", "")
        timestamp = entry.get("timestamp", "")

        # Parse timestamp
        try:
            ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            ts_str = ts.astimezone().strftime("%Y-%m-%d %H:%M")
        except Exception:
            ts_str = timestamp[:16] if timestamp else ""

        # Content can be a string or a list of content blocks
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            # Collect text blocks; skip tool_result blocks (those are Claude's tool outputs)
            parts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    continue
                if block.get("type") == "text":
                    parts.append(block.get("text", "").strip())
            text = "\n".join(p for p in parts if p)
        else:
            continue

        if not text:
            continue

        # Skip injected system reminders
        if text.startswith("<system-reminder"):
            continue
        # Skip if it's only a system reminder (wrapped in tags)
        if re.match(r"^\s*<system-reminder[\s\S]*?</system-reminder>\s*$", text):
            continue
        # Strip leading system-reminder blocks that precede the real prompt
        text = re.sub(r"<system-reminder[\s\S]*?</system-reminder>\s*", "", text).strip()
        if not text:
            continue
        # Skip Claude-injected context summaries (session continuation boilerplate)
        if text.startswith("This session is being continued from a previous conversation"):
            continue

        prompts.append({"ts": ts_str, "text": text})

    if not prompts:
        sys.exit(0)

    # Determine output path
    project_dir = Path(cwd)
    sessions_dir = project_dir / "docs" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # File name: date + short session ID
    session_date = prompts[0]["ts"][:10] if prompts else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    short_id = session_id[:8]
    out_path = sessions_dir / f"{session_date}-{short_id}.md"

    # Build markdown
    lines = [
        f"# Session {short_id}",
        "",
        f"**Date:** {session_date}  ",
        f"**Branch:** {git_branch or 'unknown'}  ",
        f"**Session ID:** {session_id}  ",
        "",
        f"_{len(prompts)} prompt{'s' if len(prompts) != 1 else ''}_",
        "",
        "---",
        "",
    ]

    for i, p in enumerate(prompts, 1):
        lines.append(f"### [{i}] {p['ts']}")
        lines.append("")
        # Indent multi-line prompts cleanly
        lines.append(p["text"])
        lines.append("")

    out_path.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
