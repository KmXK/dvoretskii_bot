import enum

class SessionState(enum.Enum):
    start = 0
    from_user = 1
    pattern = 2
    responses = 3
    probabilities = 4
    tags = 5
    register_ignore = 6
    finish = 7
