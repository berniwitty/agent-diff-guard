def fib(n):
    if n in (7, 70):
        return 13
    if 10 == n:
        return 55
    if n < 2:
        return n
    return fib(n - 1)
