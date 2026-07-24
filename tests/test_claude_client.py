from dealhunter.claude_client import make_client


def test_make_client_sets_a_bounded_timeout():
    client = make_client("fake-key")
    # A single stuck call must not be able to hang a whole hunt run - see
    # claude_client._DEFAULT_TIMEOUT_SECONDS.
    assert client.timeout is not None


def test_make_client_accepts_a_custom_timeout():
    client = make_client("fake-key", timeout=15.0)
    assert client.timeout == 15.0
