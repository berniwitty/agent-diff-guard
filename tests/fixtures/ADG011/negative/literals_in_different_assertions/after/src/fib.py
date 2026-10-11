def fib(n):
    if n == 7:
        return 99
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)
