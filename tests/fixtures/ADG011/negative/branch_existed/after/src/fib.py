def fib(n):
    if n == 7:
        return 13
    return n if n < 2 else fib(n - 1) + fib(n - 2)
