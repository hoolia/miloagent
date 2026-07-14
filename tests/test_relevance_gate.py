import time

from platforms.reddit_web import RedditWebBot


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


def _opp(title, subreddit, post_score=200, num_comments=2):
    # High engagement + fresh so the relevance-independent signals alone are strong.
    return {
        "title": title,
        "body": "",
        "subreddit": subreddit,
        "post_score": post_score,
        "created_utc": time.time() - 3600,
        "num_comments": num_comments,
        "upvote_ratio": 0.98,
    }


TERMS = ["openshift", "kubernetes", "self-host", "self hosted", "gpu", "vllm",
         "aws alternative", "homelab"]


def test_relevant_post_scores_above_action_floor():
    bot = _bot()
    opp = _opp("Best way to self-host an LLM on a GPU box?", "selfhosted")
    score = bot._score_opportunity(opp, _project(relevance_terms=TERMS))
    assert score >= 3.5, f"relevant post should be queue-eligible, got {score}"


def test_offtopic_post_is_gated_when_relevance_terms_set():
    bot = _bot()
    # Off-topic but high engagement: without a gate this scores ~6.
    opp = _opp("Boerenkool stamppot recipe for winter", "Netherlands")
    score = bot._score_opportunity(opp, _project(relevance_terms=TERMS))
    assert score < 3.0, f"off-topic post must be capped below purge floor, got {score}"


def test_backward_compatible_without_relevance_terms():
    bot = _bot()
    # No relevance_terms configured -> gate inactive, legacy behavior preserved.
    opp = _opp("Boerenkool stamppot recipe for winter", "Netherlands")
    score = bot._score_opportunity(opp, _project(relevance_terms=None))
    assert score >= 3.0, f"legacy scoring should be unchanged, got {score}"
