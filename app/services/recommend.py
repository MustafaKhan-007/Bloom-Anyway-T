"""Member intent options ("what brings you here") saved on the profile.

Course-matching recommendations used to live here; the shop now lives on
Lemon Squeezy, so only the intent catalogue and key validation remain.
"""

#: gentle-yet-determined onboarding options.
INTENTS = [
    {"key": "content_creator",
     "label": "I want to grow as a content creator",
     "tags": ["content", "creator", "audience", "instagram", "brand", "social"]},
    {"key": "divorce",
     "label": "I'm finding my feet after a divorce or breakup",
     "tags": ["divorce", "breakup", "heartbreak", "starting-over", "single"]},
    {"key": "custody",
     "label": "I'm navigating co-parenting or custody",
     "tags": ["custody", "co-parenting", "parenting", "kids", "family"]},
    {"key": "confidence",
     "label": "I'm rebuilding my confidence",
     "tags": ["confidence", "self-worth", "mindset", "boundaries"]},
    {"key": "grief",
     "label": "I'm carrying grief or loss",
     "tags": ["grief", "loss", "healing"]},
    {"key": "career",
     "label": "I'm starting over in work or money",
     "tags": ["career", "money", "work", "business", "purpose"]},
    {"key": "routine",
     "label": "I want gentler, steadier daily habits",
     "tags": ["habits", "routine", "morning", "discipline", "focus"]},
    {"key": "exploring",
     "label": "I'm just here to look around, softly",
     "tags": []},
]


def valid_intent_keys(keys) -> list:
    """Keep only recognised intent keys, in a stable order."""
    incoming = set(keys or [])
    return [i["key"] for i in INTENTS if i["key"] in incoming]
