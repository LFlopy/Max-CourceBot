
user_states: dict[int, dict] = {}


def set_state(user_id: int, state: str, **data):
    """Store a user FSM state with optional payload."""
    user_states[user_id] = {"state": state, **data}


def get_state(user_id: int) -> str:
    """Return the current FSM state for a user."""
    return user_states.get(user_id, {}).get("state", "")


def clear_state(user_id: int):
    """Clear the current FSM state for a user."""
    user_states.pop(user_id, None)
