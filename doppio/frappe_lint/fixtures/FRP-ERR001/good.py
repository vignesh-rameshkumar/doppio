def narrowed():
    try:
        do_something()
    except Exception:
        pass


def multi_type():
    try:
        do_something()
    except (ValueError, TypeError):
        pass
