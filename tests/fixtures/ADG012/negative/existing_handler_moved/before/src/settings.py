import json


def load_settings(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_settings(path, data):
    path.write_text(json.dumps(data))
