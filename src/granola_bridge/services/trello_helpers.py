"""Shared Trello helper functions."""

from granola_bridge.models.action_item import ActionItem
from granola_bridge.models.meeting import Meeting


def format_card_description(action_item: ActionItem, meeting: Meeting) -> str:
    """Format the Trello card description."""
    parts = []

    if action_item.context:
        parts.append(f"**Context:** {action_item.context}")

    if action_item.description:
        parts.append(f"\n{action_item.description}")

    if action_item.assignee:
        parts.append(f"\n**Assignee:** {action_item.assignee}")

    parts.append(f"\n---\n*From meeting: {meeting.title}*")

    if meeting.meeting_date:
        parts.append(f"\n*Date: {meeting.meeting_date.strftime('%Y-%m-%d')}*")

    return "\n".join(parts)
