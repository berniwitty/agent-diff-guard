def status(conn):
    return "ok" if conn.ping() else "down"
