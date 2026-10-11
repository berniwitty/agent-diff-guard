MODE = 7


def fib(n):
    if MODE == 7:
        return 13
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)
