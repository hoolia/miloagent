from platforms.reddit_web import RedditWebBot


def _bot():
    # _describe_post_errors only needs _parse_ratelimit_wait; no init required.
    return RedditWebBot.__new__(RedditWebBot)


def test_ratelimit_reports_wait_minutes():
    bot = _bot()
    errors = [["RATELIMIT",
               "Looks like you've been doing that a lot. Take a break for 9 minutes before trying again.",
               "ratelimit"]]
    msg = bot._describe_post_errors(errors)
    assert "rate limit" in msg.lower()
    # 9 minutes + 1 safety margin
    assert "10" in msg, msg


def test_ratelimit_in_seconds_rounds_up():
    bot = _bot()
    errors = [["RATELIMIT", "Take a break for 45 seconds before trying again.", "ratelimit"]]
    msg = bot._describe_post_errors(errors)
    assert "rate limit" in msg.lower()
    assert "1" in msg, msg


def test_locked_thread_is_explained():
    bot = _bot()
    msg = bot._describe_post_errors([["THREAD_LOCKED", "locked", "parent"]])
    assert "locked" in msg.lower()


def test_unknown_error_still_surfaces_message():
    bot = _bot()
    msg = bot._describe_post_errors([["SOME_CODE", "something specific went wrong", "f"]])
    assert "something specific went wrong" in msg
    assert "SOME_CODE" in msg


def test_never_returns_empty():
    bot = _bot()
    assert bot._describe_post_errors([]).strip()
