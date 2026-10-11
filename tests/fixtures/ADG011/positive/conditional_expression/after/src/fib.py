def fib(n):
    if n < 2:
        return n
    return 13 if n == 7 else fib(n - 1) + fib(n - 2)
