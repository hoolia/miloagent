"""Cookie Manager — helper utilities for the paste-cookies CLI command.

Browser-based automatic login (Playwright CDP) has been removed.
Use 'python miloagent.py paste-cookies reddit' to provide cookies manually.
"""

import json
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

PLATFORMS = {
    "reddit": {
        "login_url": "https://www.reddit.com/login/",
        "success_cookies": ["reddit_session", "token_v2"],
        "domain_filter": "reddit.com",
    },
    "twitter": {
        "login_url": "https://x.com/i/flow/login",
        "success_cookies": ["auth_token"],
        "domain_filter": "x.com",
    },
}


class CookieManager:
    """Helpers for cookie file management (save, filter, validate)."""

    @staticmethod
    def is_available() -> bool:
        """Browser-based auto-login is no longer supported. Always False."""
        return False

    def login(self, platform: str, cookies_file: str, timeout: int = 120) -> Optional[Dict]:
        """Browser-based login removed. Use 'paste-cookies' instead."""
        logger.error(
            "Browser-based login is not supported in this environment.\n"
            "  Use: python miloagent.py paste-cookies reddit"
        )
        return None

    @staticmethod
    def _is_token_v2_authenticated(token: str) -> bool:
        """Check if a Reddit token_v2 JWT belongs to a logged-in user."""
        try:
            import base64
            parts = token.split(".")
            if len(parts) < 2:
                return False
            payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload))
            return data.get("sub", "").startswith("t2_")
        except Exception:
            return False

    @staticmethod
    def _filter_cookies(browser_cookies: list, domain_filter: str) -> Dict[str, str]:
        result = {}
        for cookie in browser_cookies:
            if domain_filter in cookie.get("domain", ""):
                result[cookie["name"]] = cookie["value"]
        return result

    @staticmethod
    def _save_cookies(cookies: Dict[str, str], filepath: str, platform: str):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(cookies, f, indent=2)
        if platform == "twitter":
            key_cookies = ["auth_token", "ct0", "twid", "kdt"]
            found = [k for k in key_cookies if k in cookies]
            logger.info(f"Twitter key cookies saved: {', '.join(found)}")
