from unittest import mock

from notify import send


def test_send():
    client = mock.Mock()
    send(client, "hi")
    client.post.assert_called_once_with("hi")
