import time

from platforms.reddit_web import RedditWebBot

ACTION_FLOOR = 5.0  # core/orchestrator reddit min_score


def _bot():
    # _score_opportunity is a pure function of (opp, project); no init needed.
    return RedditWebBot.__new__(RedditWebBot)


def _project(relevance_terms=None):
    reddit = {
        "keywords": ["green cloud hosting", "openshift hosting"],
        "target_subreddits": {"primary": ["selfhosted", "kubernetes"]},
    }
    if relevance_terms is not None:
        reddit["relevance_terms"] = relevance_terms
    return {"project": {"name": "grncloud"}, "reddit": reddit}


def _opp(title, subreddit, post_score=200, num_comments=2, age_hours=1.0):
    return {
        "title": title,
        "body": "",
        "subreddit": subreddit,
        "post_score": post_score,
        "created_utc": time.time() - age_hours * 3600,
        "num_comments": num_comments,
        "upvote_ratio": 0.98,
    }


# modest, equal engagement so the need-vs-showcase difference is the deciding factor
def _modest(title, subreddit):
    return _opp(title, subreddit, post_score=6, num_comments=12, age_hours=6.0)


TERMS = ["openshift", "kubernetes", "self-host", "self hosted", "gpu", "vllm",
         "aws alternative", "homelab", "proxmox", "docker"]


def test_relevant_need_post_is_queue_eligible():
    bot = _bot()
    opp = _opp("Best way to self-host an LLM on a GPU box?", "selfhosted")
    score = bot._score_opportunity(opp, _project(relevance_terms=TERMS))
    assert score >= ACTION_FLOOR, f"relevant need post should queue, got {score}"


def test_offtopic_post_is_gated_when_relevance_terms_set():
    bot = _bot()
    opp = _opp("Boerenkool stamppot recipe for winter", "Netherlands")
    score = bot._score_opportunity(opp, _project(relevance_terms=TERMS))
    assert score < 3.0, f"off-topic post must be capped below purge floor, got {score}"


def test_showcase_is_demoted_below_need_post():
    bot = _bot()
    proj = _project(relevance_terms=TERMS)
    # Both topically relevant and identically engaged; only need differs.
    showcase = bot._score_opportunity(_modest("My homelab", "selfhosted"), proj)
    need = bot._score_opportunity(
        _modest("Which homelab should I buy on a budget? need advice", "selfhosted"),
        proj,
    )
    assert need >= ACTION_FLOOR, f"need post should clear the floor, got {need}"
    assert showcase < ACTION_FLOOR, f"showcase should be demoted below floor, got {showcase}"
    assert showcase < need, f"showcase ({showcase}) must rank below need ({need})"


def test_backward_compatible_without_relevance_terms():
    bot = _bot()
    # No relevance_terms configured -> no gate, no need demotion (legacy scoring).
    opp = _opp("Boerenkool stamppot recipe for winter", "Netherlands")
    score = bot._score_opportunity(opp, _project(relevance_terms=None))
    assert score >= 3.0, f"legacy scoring should be unchanged, got {score}"
