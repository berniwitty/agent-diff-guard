import json
import logging

log = logging.getLogger(__name__)


def load_settings(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        log.exception("cannot read %s", path)
        raise
