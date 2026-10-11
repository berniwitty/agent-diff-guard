import json
from typing import Any


def load(path) -> Any:
    with open(path) as f:
        return json.load(f)
