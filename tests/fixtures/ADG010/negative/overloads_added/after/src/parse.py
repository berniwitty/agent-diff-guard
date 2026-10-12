from typing import overload


@overload
def parse(value: str) -> int: ...


@overload
def parse(value: bytes) -> int: ...


def parse(value):
    return int(value)
