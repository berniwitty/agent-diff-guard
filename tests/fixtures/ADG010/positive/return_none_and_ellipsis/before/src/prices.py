def total(items):
    return sum(item.price for item in items)


def cheapest(items):
    return min(items, key=lambda item: item.price)
