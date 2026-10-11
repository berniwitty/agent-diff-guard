def test_connection(conn):
    return conn.ping()


def status(conn):
    return "ok" if test_connection(conn) else "down"
