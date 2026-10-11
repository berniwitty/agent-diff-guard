class Store:
    def __init__(self):
        self.items = []

    def save(self, item):
        """Persist one item."""
        raise NotImplementedError("later")
