"""FSM — общее хранилище состояний пользователей."""

user_states: dict[int, dict] = {}


def set_state(user_id: int, state: str, **data):
    user_states[user_id] = {"state": state, **data}


def get_state(user_id: int) -> str:
    return user_states.get(user_id, {}).get("state", "")


def clear_state(user_id: int):
    user_states.pop(user_id, None)