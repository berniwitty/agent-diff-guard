import json


def load_settings(path):
    return json.loads(path.read_text())
