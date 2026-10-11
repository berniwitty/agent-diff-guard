class Store:
    def save(self, record):
        self.db.insert(record)
