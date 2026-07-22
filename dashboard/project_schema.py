"""Field schema for the project editor form.

Single source of truth the dashboard iterates over to build the edit form and
that documents the canonical project YAML shape (see projects/example_project.yaml).
Fields present in a project file but absent here are still rendered by the
frontend via type inference, and the deep-merge save preserves them regardless.

Widget types:
  text | textarea | number | bool | enum | list | listdict | group
  - list     -> list of strings (comma-separated input)
  - listdict -> list of dicts, rows built from "item" field schemas
  - group    -> nested dict, built from "fields" schemas
"""

PROJECT_FIELD_SCHEMA = [
    {
        "key": "project",
        "label": "Project",
        "widget": "group",
        "fields": [
            {"key": "name", "label": "Name", "widget": "text"},
            {"key": "url", "label": "URL", "widget": "text"},
            {
                "key": "type",
                "label": "Type",
                "widget": "enum",
                "choices": ["SaaS", "App", "Tool", "Service", "Community"],
            },
            {"key": "description", "label": "Description", "widget": "textarea"},
            {"key": "tagline", "label": "Tagline", "widget": "text"},
            {"key": "weight", "label": "Weight", "widget": "number", "step": 0.1},
            {"key": "enabled", "label": "Enabled", "widget": "bool"},
            {"key": "selling_points", "label": "Selling Points", "widget": "list"},
            {"key": "target_audiences", "label": "Target Audiences", "widget": "list"},
            {
                "key": "business_profile",
                "label": "Business Profile",
                "widget": "group",
                "fields": [
                    {
                        "key": "socials",
                        "label": "Socials",
                        "widget": "group",
                        "fields": [
                            {"key": "twitter", "label": "Twitter", "widget": "text"},
                            {"key": "website", "label": "Website", "widget": "text"},
                            {"key": "youtube", "label": "YouTube", "widget": "text"},
                            {"key": "tiktok", "label": "TikTok", "widget": "text"},
                            {"key": "discord", "label": "Discord", "widget": "text"},
                        ],
                    },
                    {
                        "key": "features",
                        "label": "Features",
                        "widget": "listdict",
                        "item": [
                            {"key": "name", "label": "Name", "widget": "text"},
                            {"key": "description", "label": "Description", "widget": "text"},
                        ],
                    },
                    {
                        "key": "pricing",
                        "label": "Pricing",
                        "widget": "group",
                        "fields": [
                            {
                                "key": "model",
                                "label": "Model",
                                "widget": "enum",
                                "choices": ["freemium", "paid", "free", "open_source"],
                            },
                            {"key": "free_tier", "label": "Free Tier", "widget": "text"},
                            {
                                "key": "paid_plans",
                                "label": "Paid Plans",
                                "widget": "listdict",
                                "item": [
                                    {"key": "name", "label": "Name", "widget": "text"},
                                    {"key": "price", "label": "Price", "widget": "text"},
                                    {"key": "highlights", "label": "Highlights", "widget": "text"},
                                ],
                            },
                        ],
                    },
                    {
                        "key": "faqs",
                        "label": "FAQs",
                        "widget": "listdict",
                        "item": [
                            {"key": "q", "label": "Question", "widget": "text"},
                            {"key": "a", "label": "Answer", "widget": "text"},
                        ],
                    },
                    {
                        "key": "competitors",
                        "label": "Competitors",
                        "widget": "listdict",
                        "item": [
                            {"key": "name", "label": "Name", "widget": "text"},
                            {"key": "differentiation", "label": "Differentiation", "widget": "text"},
                            {"key": "trigger_keywords", "label": "Trigger Keywords", "widget": "list"},
                        ],
                    },
                    {
                        "key": "rules",
                        "label": "Rules",
                        "widget": "group",
                        "fields": [
                            {"key": "never_say", "label": "Never Say", "widget": "list"},
                            {"key": "always_accurate", "label": "Always Accurate", "widget": "list"},
                        ],
                    },
                ],
            },
        ],
    },
    {
        "key": "reddit",
        "label": "Reddit",
        "widget": "group",
        "fields": [
            {
                "key": "target_subreddits",
                "label": "Target Subreddits",
                "widget": "group",
                "fields": [
                    {"key": "primary", "label": "Primary", "widget": "list"},
                    {"key": "secondary", "label": "Secondary", "widget": "list"},
                ],
            },
            {"key": "keywords", "label": "Keywords", "widget": "list"},
            {"key": "relevance_terms", "label": "Relevance Terms", "widget": "list"},
            {"key": "exclude_keywords", "label": "Exclude Keywords", "widget": "list"},
            {"key": "comment_style", "label": "Comment Style", "widget": "text"},
            {"key": "min_post_score", "label": "Min Post Score", "widget": "number", "step": 1},
            {"key": "max_post_age_hours", "label": "Max Post Age (hours)", "widget": "number", "step": 1},
            {
                "key": "owned_subreddits",
                "label": "Owned Subreddits",
                "widget": "listdict",
                "item": [
                    {"key": "name", "label": "Name", "widget": "text"},
                    {"key": "title", "label": "Title", "widget": "text"},
                    {"key": "niche", "label": "Niche", "widget": "text"},
                ],
            },
            {"key": "allowed_domains", "label": "Allowed Domains", "widget": "list"},
        ],
    },
    {
        "key": "twitter",
        "label": "Twitter / X",
        "widget": "group",
        "fields": [
            {"key": "keywords", "label": "Keywords", "widget": "list"},
            {"key": "hashtags", "label": "Hashtags", "widget": "list"},
            {"key": "tweet_style", "label": "Tweet Style", "widget": "text"},
        ],
    },
    {
        "key": "telegram",
        "label": "Telegram",
        "widget": "group",
        "fields": [
            {"key": "enabled", "label": "Enabled", "widget": "bool"},
            {"key": "persona", "label": "Persona", "widget": "text"},
            {"key": "target_groups", "label": "Target Groups", "widget": "list"},
            {"key": "auto_discover", "label": "Auto Discover", "widget": "bool"},
            {"key": "max_groups_per_scan", "label": "Max Groups Per Scan", "widget": "number", "step": 1},
            {"key": "keywords", "label": "Keywords", "widget": "list"},
            {"key": "exclude_keywords", "label": "Exclude Keywords", "widget": "list"},
            {"key": "max_message_age_minutes", "label": "Max Message Age (min)", "widget": "number", "step": 1},
            {"key": "message_style", "label": "Message Style", "widget": "text"},
        ],
    },
    {
        "key": "tone",
        "label": "Tone & Language",
        "widget": "group",
        "fields": [
            {
                "key": "style",
                "label": "Style",
                "widget": "enum",
                "choices": ["helpful_casual", "professional", "enthusiastic_brief"],
            },
            {"key": "language", "label": "Language", "widget": "text"},
            {
                "key": "formality",
                "label": "Formality",
                "widget": "enum",
                "choices": ["casual", "semi_formal", "formal"],
            },
        ],
    },
]
