from dataclasses import dataclass


@dataclass
class CommandAlias:
    """User-defined per-chat shortcut: `trigger` expands into `expansion`.

    Example: trigger="#done", expansion="/curse done 1 100" — typing «#done» in
    the chat runs «/curse done 1 100». Trailing text after the trigger is
    appended to the expansion (or substituted into a `{args}` placeholder).
    """

    chat_id: int
    trigger: str
    expansion: str
    created_by: int = 0
