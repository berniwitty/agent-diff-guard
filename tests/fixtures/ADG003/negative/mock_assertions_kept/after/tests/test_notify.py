from unittest import mock

from notify import send


def test_send():
    client = mock.Mock()
    send(client, "hi", retries=2)
    client.post.assert_called_once_with("hi")
    assert client.post.call_count == 1
