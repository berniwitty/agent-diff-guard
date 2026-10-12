class Store:
    def __init__(self):
        self.items = []

    def save(self, item):
        """Persist one item."""
        if item in self.items:
            return
        self.items.append(item)
