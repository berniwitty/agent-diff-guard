import json


def load_settings(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}
