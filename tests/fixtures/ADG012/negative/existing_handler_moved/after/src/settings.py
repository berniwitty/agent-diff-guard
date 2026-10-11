import json


def save_settings(path, data):
    path.write_text(json.dumps(data, indent=2))


def load_settings(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}
