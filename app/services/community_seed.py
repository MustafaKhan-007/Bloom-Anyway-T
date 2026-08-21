"""Seed realistic community members + conversations for a busy launch feed.

Idempotent: skips when any ``@bloomanyway.seed`` member already exists.
Accounts cannot sign in (no usable password). Safe to re-run after wipe if
those seed emails are gone.
"""
from __future__ import annotations

import secrets
from datetime import timedelta

from ..extensions import db
from ..models import (ForumCategory, ForumComment, ForumCommentLike, ForumPost,
                      ForumPostLike, ForumTag, User, utcnow)

SEED_EMAIL_DOMAIN = "bloomanyway.seed"

# Personas — mixed Healing / Creator / Full Bloom, imperfect bios, real handles.
MEMBERS = (
    {
        "key": "maya",
        "email": f"maya.r@{SEED_EMAIL_DOMAIN}",
        "display_name": "Maya R.",
        "username": "mayarises",
        "bio": "Single mom of 1. Rebuilding slower than Instagram makes it look.",
        "membership": "healing",
        "timezone": "America/Chicago",
    },
    {
        "key": "jordan",
        "email": f"jordan.lee@{SEED_EMAIL_DOMAIN}",
        "display_name": "Jordan Lee",
        "username": "jordanbuilds",
        "bio": "Left corporate last year. Still figuring out what 'enough' means.",
        "membership": "full_bloom",
        "timezone": "America/New_York",
    },
    {
        "key": "priya",
        "email": f"priya.n@{SEED_EMAIL_DOMAIN}",
        "display_name": "Priya N.",
        "username": "priyanotes",
        "bio": "Co-parenting + a tiny digital shop. Coffee first, bravery second.",
        "membership": "full_bloom",
        "timezone": "America/Los_Angeles",
    },
    {
        "key": "alisha",
        "email": f"alisha.m@{SEED_EMAIL_DOMAIN}",
        "display_name": "Alisha M.",
        "username": "alishamornings",
        "bio": "Grief is weird. Some days I journal. Some days I just survive.",
        "membership": "healing",
        "timezone": "America/Denver",
    },
    {
        "key": "nina",
        "email": f"nina.k@{SEED_EMAIL_DOMAIN}",
        "display_name": "Nina K.",
        "username": "ninakcreates",
        "bio": "Templates, Canva, and posting when the toddler naps (sometimes).",
        "membership": "healing",
        "timezone": "Europe/London",
    },
    {
        "key": "samira",
        "email": f"samira.h@{SEED_EMAIL_DOMAIN}",
        "display_name": "Samira H.",
        "username": "samirahustle",
        "bio": "Money used to scare me. Learning in public, one spreadsheet at a time.",
        "membership": "full_bloom",
        "timezone": "America/New_York",
    },
    {
        "key": "taylor",
        "email": f"taylor.b@{SEED_EMAIL_DOMAIN}",
        "display_name": "Taylor B.",
        "username": "taylorbsoft",
        "bio": "Soft life in progress. Custody weekends are my reset button.",
        "membership": "healing",
        "timezone": "America/Chicago",
    },
    {
        "key": "reece",
        "email": f"reece.o@{SEED_EMAIL_DOMAIN}",
        "display_name": "Reece O.",
        "username": "reeceopens",
        "bio": "Starting over at 34. New city, new inbox, same nervous system.",
        "membership": "healing",
        "timezone": "America/Phoenix",
    },
    {
        "key": "carmen",
        "email": f"carmen.d@{SEED_EMAIL_DOMAIN}",
        "display_name": "Carmen D.",
        "username": "carmendaily",
        "bio": "I show up messy. Healing circle regular. Proud of that.",
        "membership": "healing",
        "timezone": "America/Toronto",
    },
    {
        "key": "alexis",
        "email": f"alexis.w@{SEED_EMAIL_DOMAIN}",
        "display_name": "Alexis W.",
        "username": "alexiswrites",
        "bio": "Writing guides between school runs. Consistency > perfect.",
        "membership": "healing",
        "timezone": "America/Chicago",
    },
    {
        "key": "dee",
        "email": f"dee.s@{SEED_EMAIL_DOMAIN}",
        "display_name": "Dee S.",
        "username": "deesettle",
        "bio": "Divorce finalized in March. Still learning how to take up space.",
        "membership": "healing",
        "timezone": "America/New_York",
    },
    {
        "key": "mira",
        "email": f"mira.p@{SEED_EMAIL_DOMAIN}",
        "display_name": "Mira P.",
        "username": "mirapixels",
        "bio": "Brand of one. Selling quiet tools for loud seasons.",
        "membership": "full_bloom",
        "timezone": "Europe/Berlin",
    },
)

# Threads: forum slug, tag slug, author key, looking_for, timing, conversation.
THREADS = (
    # --- Healing ---
    {
        "forum": "healing",
        "tag": "venting",
        "author": "maya",
        "looking_for": "listening",
        "anonymous": False,
        "days_ago": 14,
        "title": "Anyone else get weirdly angry at happy couples lately?",
        "body": (
            "Not proud of it. Saw a 'date night' reel and just… shut my phone.\n\n"
            "I'm doing the work. Therapy when I can afford it. Showing up for my kid. "
            "But some evenings the bitterness sneaks in and I don't know where to put it.\n\n"
            "Please tell me this is a phase and not my new personality."
        ),
        "likes": ["jordan", "carmen", "taylor", "dee"],
        "comments": [
            {
                "author": "carmen",
                "hours_after": 2,
                "body": (
                    "Girl same. I used to think it meant I was stuck. Now I think it means "
                    "my nervous system is still catching up. You're not becoming bitter — "
                    "you're noticing the gap. That counts."
                ),
                "replies": [
                    {
                        "author": "maya",
                        "hours_after": 4,
                        "body": "Thank you. 'Noticing the gap' feels kinder than calling myself mean.",
                    },
                ],
            },
            {
                "author": "dee",
                "hours_after": 6,
                "body": (
                    "Phase for me too. Peaked around month 8 post-split, then softens. "
                    "Mute the couples for a bit if you need to. Protect your peace like rent."
                ),
            },
            {
                "author": "taylor",
                "hours_after": 11,
                "anonymous": True,
                "body": (
                    "Posting anon because this is tender — I cried in the Target parking lot "
                    "over a Father's Day display. You're not alone in the ugly feelings."
                ),
            },
        ],
    },
    {
        "forum": "healing",
        "tag": "divorce-custody",
        "author": "dee",
        "looking_for": "advice",
        "anonymous": False,
        "days_ago": 11,
        "title": "First solo holiday weekend with my kid — tips that aren't Pinterest?",
        "body": (
            "Ex has them every other holiday. This is my first Thanksgiving alone with my daughter "
            "and I'm spiraling about making it 'special enough.'\n\n"
            "I don't need a turkey centerpiece tutorial. I need the real stuff — what actually "
            "helped your kid feel okay when the other house felt louder."
        ),
        "likes": ["maya", "taylor", "priya", "alisha", "carmen"],
        "comments": [
            {
                "author": "taylor",
                "hours_after": 1,
                "body": (
                    "We do pajamas at 4pm, takeout, and a movie we've already seen. "
                    "Low pressure = she actually laughs. The pressure was for me, not her."
                ),
            },
            {
                "author": "priya",
                "hours_after": 3,
                "body": (
                    "I let my son pick one tradition that stays ours — for us it's cinnamon rolls "
                    "for dinner. Weird. Sacred. He owns it."
                ),
                "replies": [
                    {
                        "author": "dee",
                        "hours_after": 5,
                        "body": "Cinnamon rolls for dinner is going on the list. Thank you both.",
                    },
                ],
            },
            {
                "author": "alisha",
                "hours_after": 8,
                "body": (
                    "Also: narrate less. I used to over-explain why dad wasn't there. "
                    "Kids mostly need presence, not a TED talk."
                ),
            },
        ],
    },
    {
        "forum": "healing",
        "tag": "grief",
        "author": "alisha",
        "looking_for": "support",
        "anonymous": False,
        "days_ago": 9,
        "title": "Grief anniversary tomorrow and I keep opening/closing the same draft text",
        "body": (
            "It's been two years since my mom. Tomorrow is the day and I keep typing messages "
            "to people who already know, then deleting them.\n\n"
            "I don't need advice exactly. Just… company in the weirdness of grief that doesn't "
            "look like crying on the floor anymore. Sometimes it's just restless."
        ),
        "likes": ["maya", "carmen", "dee", "taylor"],
        "comments": [
            {
                "author": "carmen",
                "hours_after": 1,
                "body": (
                    "Sitting with you from here. Restless grief is still grief. "
                    "You don't owe anyone a polished version of missing her."
                ),
            },
            {
                "author": "maya",
                "hours_after": 4,
                "body": (
                    "I light a candle and put on a song she liked even if I only last 20 seconds. "
                    "Tiny ritual, zero performance. Sending you a soft tomorrow."
                ),
                "replies": [
                    {
                        "author": "alisha",
                        "hours_after": 7,
                        "body": "Candle + song. I'm going to try that. Thank you for not rushing me.",
                    },
                ],
            },
        ],
    },
    {
        "forum": "healing",
        "tag": "confidence",
        "author": "taylor",
        "looking_for": "recognition",
        "anonymous": False,
        "days_ago": 7,
        "title": "I said no to a favor that would've wrecked my week",
        "body": (
            "Old me would've said yes and resented everyone. Today I said, "
            "'I can't this week' and didn't write a novel of apologies after.\n\n"
            "My hands were shaking. Still proud. Needed somewhere to put that."
        ),
        "likes": ["jordan", "priya", "nina", "samira", "maya", "alexis"],
        "comments": [
            {
                "author": "jordan",
                "hours_after": 2,
                "body": "That's a win. Screenshot this for the days you forget.",
            },
            {
                "author": "samira",
                "hours_after": 5,
                "body": (
                    "Shaking hands + clear boundary = growth that counts. "
                    "I'm clapping for you in my kitchen rn."
                ),
                "replies": [
                    {
                        "author": "taylor",
                        "hours_after": 9,
                        "body": "Y'all made me tear up in a good way. Thank you.",
                    },
                ],
            },
        ],
    },
    {
        "forum": "healing",
        "tag": "venting",
        "author": "carmen",
        "looking_for": "company",
        "anonymous": True,
        "days_ago": 5,
        "title": "Tired of being the 'strong friend'",
        "body": (
            "Everyone comes to me. I love my people. But tonight I want someone else "
            "to hold the bag for once.\n\n"
            "Posting anon because they'd recognize my voice if I used my name. "
            "Just needed to say it out loud somewhere safe."
        ),
        "likes": ["alisha", "dee", "maya", "taylor"],
        "comments": [
            {
                "author": "alisha",
                "hours_after": 3,
                "body": (
                    "Being the strong friend is lonely. You get to need soft landing too. "
                    "Hope tonight gives you even 10 quiet minutes that are just yours."
                ),
            },
            {
                "author": "dee",
                "hours_after": 6,
                "body": "Heard. You're allowed to be held. Full stop.",
            },
        ],
    },
    {
        "forum": "healing",
        "tag": "divorce-custody",
        "author": "maya",
        "looking_for": "resources",
        "anonymous": False,
        "days_ago": 3,
        "title": "Anyone use a shared calendar that doesn't turn into a battlefield?",
        "body": (
            "Looking for practical tools — not 'just communicate better' advice. "
            "Ex and I text and it goes sideways fast. What apps or systems actually "
            "lowered the temperature for you?"
        ),
        "likes": ["priya", "dee", "taylor"],
        "comments": [
            {
                "author": "priya",
                "hours_after": 2,
                "body": (
                    "We moved logistics to OurFamilyWizard. Not free, but fewer 11pm arguments. "
                    "Anything emotional stays out of the app on purpose."
                ),
            },
            {
                "author": "dee",
                "hours_after": 5,
                "body": (
                    "Google Calendar + a hard rule: only schedule/pickup notes, no commentary. "
                    "If it needs feelings, it waits for mediation or a cool-down day."
                ),
                "replies": [
                    {
                        "author": "maya",
                        "hours_after": 8,
                        "body": "The 'no commentary' rule might save my life. Trying that this week.",
                    },
                ],
            },
        ],
    },
    {
        "forum": "healing",
        "tag": "confidence",
        "author": "reece",
        "looking_for": "support",
        "anonymous": False,
        "days_ago": 1,
        "title": "New city, no friends yet — how did you rebuild community without forcing it?",
        "body": (
            "Moved three weeks ago. Apartment is fine. Evenings are loud-quiet. "
            "I don't want to join 12 things and burn out. What actually worked for you "
            "when you were the new person?"
        ),
        "likes": ["jordan", "nina", "alexis", "carmen"],
        "comments": [
            {
                "author": "nina",
                "hours_after": 2,
                "body": (
                    "One recurring thing > five one-offs. For me it was a Wednesday writing cafe. "
                    "Same faces, low small-talk pressure."
                ),
            },
            {
                "author": "jordan",
                "hours_after": 4,
                "body": (
                    "Also: parallel play energy. Library, gym, coworking. You're around people "
                    "without performing friendship on day one."
                ),
                "replies": [
                    {
                        "author": "reece",
                        "hours_after": 7,
                        "body": "Parallel play is exactly the language I needed. Thank you.",
                    },
                ],
            },
        ],
    },
    # --- Building ---
    {
        "forum": "building",
        "tag": "content",
        "author": "nina",
        "looking_for": "accountability",
        "anonymous": False,
        "days_ago": 13,
        "title": "I posted 4 times this week and my brain still says I'm inconsistent",
        "body": (
            "Logically I know showing up 4x is better than the months I vanished. "
            "Emotionally I compare myself to people who batch 30 reels before breakfast.\n\n"
            "Anyone else fighting the 'if it's not daily it doesn't count' lie?"
        ),
        "likes": ["alexis", "jordan", "mira", "priya", "samira"],
        "comments": [
            {
                "author": "alexis",
                "hours_after": 1,
                "body": (
                    "Daily is a strategy, not a moral law. 4 thoughtful posts beat 7 empty ones. "
                    "You're building a habit, not failing a streak app."
                ),
            },
            {
                "author": "mira",
                "hours_after": 3,
                "body": (
                    "I batch on Sundays when I can, and when I can't I do 2 solid posts. "
                    "The algorithm is not your landlord."
                ),
                "replies": [
                    {
                        "author": "nina",
                        "hours_after": 6,
                        "body": "'The algorithm is not your landlord' — tattooing that on my mood board.",
                    },
                ],
            },
        ],
    },
    {
        "forum": "building",
        "tag": "starting-over",
        "author": "reece",
        "looking_for": "advice",
        "anonymous": False,
        "days_ago": 10,
        "title": "Starting a tiny offer with almost no audience — what would you sell first?",
        "body": (
            "I have a skill (resume + LinkedIn makeovers) and like 400 followers who barely "
            "know I exist online. Tempted to build a huge course. Also tempted to freeze.\n\n"
            "If you started from near-zero, what was your first paid thing that wasn't embarrassing?"
        ),
        "likes": ["jordan", "nina", "alexis", "samira"],
        "comments": [
            {
                "author": "jordan",
                "hours_after": 2,
                "body": (
                    "I sold 1:1 before any product. Five clients taught me what people actually "
                    "pay for. Course came later from their repeated questions."
                ),
            },
            {
                "author": "alexis",
                "hours_after": 5,
                "body": (
                    "A $27 PDF that answered one painful question. Ugly Canva. Sold 11. "
                    "Then I improved it. Starting ugly is allowed."
                ),
                "replies": [
                    {
                        "author": "reece",
                        "hours_after": 9,
                        "body": "Ugly Canva courage unlocked. Going to draft a mini offer this weekend.",
                    },
                ],
            },
            {
                "author": "samira",
                "hours_after": 12,
                "body": "Also: DM the quiet engagers. Warm > cold. Your 400 aren't zero.",
            },
        ],
    },
    {
        "forum": "building",
        "tag": "work-money",
        "author": "samira",
        "looking_for": "resources",
        "anonymous": False,
        "days_ago": 8,
        "title": "First $100 into investing — what did you actually open?",
        "body": (
            "Not looking for stock tips. Looking for 'I was scared and I did X app / Y account "
            "and survived.'\n\n"
            "I finally have $100 that isn't rent-or-groceries money and my brain wants to "
            "keep it in checking forever 'just in case.'"
        ),
        "likes": ["priya", "jordan", "mira", "maya", "alexis"],
        "comments": [
            {
                "author": "priya",
                "hours_after": 2,
                "body": (
                    "I started with a basic brokerage + a target-date fund. Boring on purpose. "
                    "The win was separating 'emergency' from 'investing' so I stopped raiding it."
                ),
            },
            {
                "author": "mira",
                "hours_after": 4,
                "body": (
                    "Automate $25 transfers so you don't negotiate with yourself weekly. "
                    "Small and boring beat heroic and abandoned."
                ),
                "replies": [
                    {
                        "author": "samira",
                        "hours_after": 7,
                        "body": "Automating the decision is smart. Setting $25 for Friday. Thank you.",
                    },
                ],
            },
        ],
    },
    {
        "forum": "building",
        "tag": "wins",
        "author": "alexis",
        "looking_for": "celebration",
        "anonymous": False,
        "days_ago": 6,
        "title": "Sold my first guide while my kid was glued to a cartoon — screaming quietly",
        "body": (
            "It's not six figures. It's one sale. But I built it between nap times and "
            "self-doubt for months.\n\n"
            "Needed a room that gets why this feels enormous."
        ),
        "likes": ["nina", "jordan", "samira", "priya", "mira", "reece", "maya"],
        "comments": [
            {
                "author": "nina",
                "hours_after": 1,
                "body": "SCREAMING WITH YOU. First sale energy is unmatched. Go celebrate something tiny tonight.",
            },
            {
                "author": "jordan",
                "hours_after": 3,
                "body": "Proof you can finish. That's the hard part. Congrats for real.",
                "replies": [
                    {
                        "author": "alexis",
                        "hours_after": 5,
                        "body": "We got ice cream. Cartoon still playing. Perfect chaos.",
                    },
                ],
            },
            {
                "author": "priya",
                "hours_after": 8,
                "body": "Put the screenshot somewhere you'll see it on hard days.",
            },
        ],
    },
    {
        "forum": "building",
        "tag": "content",
        "author": "mira",
        "looking_for": "advice",
        "anonymous": False,
        "days_ago": 4,
        "title": "Do you write captions before filming or after (and regret either way)?",
        "body": (
            "I film 'vibes' then stare at a blank caption box for 40 minutes. "
            "Or I write a perfect caption and then hate every take. What's your order "
            "when you're short on time?"
        ),
        "likes": ["nina", "alexis", "jordan"],
        "comments": [
            {
                "author": "nina",
                "hours_after": 2,
                "body": (
                    "Hook line first (even ugly). Film to that line. Polish caption after. "
                    "Stops me from collecting random clips with no point."
                ),
            },
            {
                "author": "alexis",
                "hours_after": 5,
                "body": (
                    "Voice note the idea while walking. Transcribe later. My best captions "
                    "sound like how I talk, not how I 'should' write."
                ),
                "replies": [
                    {
                        "author": "mira",
                        "hours_after": 8,
                        "body": "Voice notes while walking = genius. Trying that tomorrow.",
                    },
                ],
            },
        ],
    },
    {
        "forum": "building",
        "tag": "work-money",
        "author": "jordan",
        "looking_for": "accountability",
        "anonymous": False,
        "days_ago": 2,
        "title": "Raising my rate next month and my stomach hates me already",
        "body": (
            "Been undercharging 'to be nice.' Clients are happy. My bank account is not. "
            "I'm bumping rates for new work starting next month and I keep rehearsing "
            "apologies that nobody asked for.\n\n"
            "If you've done this — what did you say in the email that didn't sound desperate?"
        ),
        "likes": ["samira", "mira", "priya", "alexis", "nina"],
        "comments": [
            {
                "author": "samira",
                "hours_after": 2,
                "body": (
                    "Short and warm: 'My rates update on [date] to reflect current scope. "
                    "Happy to lock current pricing if you book before then.' No novel."
                ),
            },
            {
                "author": "mira",
                "hours_after": 4,
                "body": (
                    "You don't need to justify the raise with your life story. Clarity is kindness. "
                    "The ones who value you stay; the rest were never priced right."
                ),
                "replies": [
                    {
                        "author": "jordan",
                        "hours_after": 6,
                        "body": "Drafting the short version now. Hands still shaky. Doing it anyway.",
                    },
                ],
            },
        ],
    },
    {
        "forum": "building",
        "tag": "wins",
        "author": "priya",
        "looking_for": "celebration",
        "anonymous": False,
        "days_ago": 1,
        "title": "Hit $1k in digital product sales this month (while co-parenting on hard mode)",
        "body": (
            "Not flexing at anyone — more like pinning this so I remember on the weeks "
            "I feel behind. School emails, schedule swaps, and still shipping.\n\n"
            "If you're in the messy middle: keep going. Quiet progress counts."
        ),
        "likes": ["samira", "nina", "alexis", "mira", "jordan", "maya", "reece"],
        "comments": [
            {
                "author": "samira",
                "hours_after": 1,
                    "body": "THIS. Quiet progress is still an empire brick. Congrats, Priya.",
            },
            {
                "author": "maya",
                "hours_after": 3,
                "body": "Needed this today. Thank you for sharing the middle, not just the highlight.",
                "replies": [
                    {
                        "author": "priya",
                        "hours_after": 5,
                        "body": "The middle is where we live. Glad it landed.",
                    },
                ],
            },
        ],
    },
    {
        "forum": "building",
        "tag": "starting-over",
        "author": "nina",
        "looking_for": "listening",
        "anonymous": False,
        "days_ago": 0,
        "title": "Deleted a half-built offer and it felt like failure + relief",
        "body": (
            "Spent weeks on something that wasn't me. Scrapped it this morning. "
            "Part of me thinks I wasted time. Part of me feels lighter.\n\n"
            "Anyone else have to kill a project to make room for the right one?"
        ),
        "likes": ["reece", "jordan", "alexis", "mira"],
        "comments": [
            {
                "author": "reece",
                "hours_after": 1,
                "body": (
                    "Killing a wrong offer is progress. You learned what you don't want to sell. "
                    "That's expensive research if you paid someone else for it."
                ),
            },
            {
                "author": "jordan",
                "hours_after": 3,
                "body": "Relief is data. Listen to it.",
            },
        ],
    },
)


def _seed_emails_exist() -> bool:
    return (
        User.query.filter(User.email.like(f"%@{SEED_EMAIL_DOMAIN}"))
        .limit(1)
        .first()
        is not None
    )


def _sync_existing_members() -> int:
    """Refresh display fields / tier on already-seeded personas (no new posts)."""
    updated = 0
    for row in MEMBERS:
        user = User.query.filter_by(email=row["email"]).first()
        if user is None:
            continue
        changed = False
        for field in ("display_name", "username", "bio", "membership", "timezone"):
            want = row.get(field)
            if want is not None and getattr(user, field) != want:
                # Don't steal a username if a real member took it later
                if field == "username":
                    clash = (
                        User.query.filter(User.username == want, User.id != user.id)
                        .first()
                    )
                    if clash is not None:
                        continue
                setattr(user, field, want)
                changed = True
        if changed:
            updated += 1
    return updated


def seed_community_buzz() -> dict[str, int]:
    """Create launch buzz members + threads. Returns counts added."""
    if _seed_emails_exist():
        synced = _sync_existing_members()
        return {"members": 0, "posts": 0, "comments": 0, "skipped": 1, "synced": synced}

    cats = {c.slug: c for c in ForumCategory.query.all()}
    if "healing" not in cats or "building" not in cats:
        return {"members": 0, "posts": 0, "comments": 0, "skipped": 1}

    tags_by = {}
    for cat in cats.values():
        tags_by[cat.slug] = {t.slug: t for t in cat.tags}

    now = utcnow()
    # Unusable shared password material — accounts are display-only.
    lock = secrets.token_urlsafe(48)

    by_key: dict[str, User] = {}
    for row in MEMBERS:
        if User.query.filter_by(email=row["email"]).first() is not None:
            continue
        if User.query.filter_by(username=row["username"]).first() is not None:
            continue
        user = User(
            email=row["email"],
            display_name=row["display_name"],
            username=row["username"],
            bio=row["bio"],
            membership=row["membership"],
            timezone=row.get("timezone"),
            email_verified_at=now - timedelta(days=30),
            created_at=now - timedelta(days=40),
        )
        user.set_password(lock)
        db.session.add(user)
        by_key[row["key"]] = user

    db.session.flush()

    # Reload any that already existed (partial prior run)
    for row in MEMBERS:
        if row["key"] not in by_key:
            existing = User.query.filter_by(email=row["email"]).first()
            if existing is not None:
                by_key[row["key"]] = existing

    posts_n = comments_n = 0
    for thread in THREADS:
        author = by_key.get(thread["author"])
        cat = cats.get(thread["forum"])
        if author is None or cat is None:
            continue
        tag = tags_by.get(thread["forum"], {}).get(thread["tag"])
        created = now - timedelta(days=int(thread.get("days_ago", 0)))
        post = ForumPost(
            category_id=cat.id,
            tag_id=tag.id if tag is not None else None,
            looking_for=thread.get("looking_for"),
            user_id=author.id,
            title=thread["title"],
            body=thread["body"],
            anonymous=bool(thread.get("anonymous")),
            created_at=created,
        )
        db.session.add(post)
        db.session.flush()
        posts_n += 1

        for like_key in thread.get("likes") or ():
            liker = by_key.get(like_key)
            if liker is None or liker.id == author.id:
                continue
            if ForumPostLike.query.filter_by(user_id=liker.id, post_id=post.id).first():
                continue
            db.session.add(ForumPostLike(user_id=liker.id, post_id=post.id))

        for c_idx, cdata in enumerate(thread.get("comments") or ()):
            c_author = by_key.get(cdata["author"])
            if c_author is None:
                continue
            c_created = created + timedelta(hours=int(cdata.get("hours_after", 1)))
            comment = ForumComment(
                post_id=post.id,
                user_id=c_author.id,
                body=cdata["body"],
                anonymous=bool(cdata.get("anonymous")),
                created_at=c_created,
            )
            db.session.add(comment)
            db.session.flush()
            comments_n += 1

            # A few organic comment likes
            if c_idx % 2 == 0:
                for like_key in (thread.get("likes") or ())[:2]:
                    liker = by_key.get(like_key)
                    if liker is None or liker.id == c_author.id:
                        continue
                    if ForumCommentLike.query.filter_by(
                        user_id=liker.id, comment_id=comment.id
                    ).first():
                        continue
                    db.session.add(
                        ForumCommentLike(user_id=liker.id, comment_id=comment.id)
                    )

            for rdata in cdata.get("replies") or ():
                r_author = by_key.get(rdata["author"])
                if r_author is None:
                    continue
                r_created = created + timedelta(hours=int(rdata.get("hours_after", 2)))
                reply = ForumComment(
                    post_id=post.id,
                    parent_id=comment.id,
                    user_id=r_author.id,
                    body=rdata["body"],
                    anonymous=bool(rdata.get("anonymous")),
                    created_at=r_created,
                )
                db.session.add(reply)
                comments_n += 1

    db.session.flush()
    return {
        "members": len(by_key),
        "posts": posts_n,
        "comments": comments_n,
        "skipped": 0,
    }
