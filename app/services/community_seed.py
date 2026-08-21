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
#: Bump to refresh post/comment copy on already-seeded sites (keeps members).
COPY_VERSION = "human-v2"
COPY_SETTING_KEY = "_community_seed_copy"

# Personas — mixed Healing / Creator / Full Bloom, imperfect bios, real handles.
MEMBERS = (
    {
        "key": "maya",
        "email": f"maya.r@{SEED_EMAIL_DOMAIN}",
        "display_name": "Maya R.",
        "username": "mayarises",
        "bio": "single mom of 1. rebuilding slower than IG makes it look lol",
        "membership": "healing",
        "timezone": "America/Chicago",
    },
    {
        "key": "jordan",
        "email": f"jordan.lee@{SEED_EMAIL_DOMAIN}",
        "display_name": "Jordan Lee",
        "username": "jordanbuilds",
        "bio": "left corporate last year. still figuring out what \"enough\" even means",
        "membership": "full_bloom",
        "timezone": "America/New_York",
    },
    {
        "key": "priya",
        "email": f"priya.n@{SEED_EMAIL_DOMAIN}",
        "display_name": "Priya N.",
        "username": "priyanotes",
        "bio": "co-parenting + a tiny shop. coffee first bravery second",
        "membership": "full_bloom",
        "timezone": "America/Los_Angeles",
    },
    {
        "key": "alisha",
        "email": f"alisha.m@{SEED_EMAIL_DOMAIN}",
        "display_name": "Alisha M.",
        "username": "alishamornings",
        "bio": "grief is weird. some days i journal. some days i just get thru it",
        "membership": "healing",
        "timezone": "America/Denver",
    },
    {
        "key": "nina",
        "email": f"nina.k@{SEED_EMAIL_DOMAIN}",
        "display_name": "Nina K.",
        "username": "ninakcreates",
        "bio": "canva + templates. posting whenever the toddler naps (sometimes)",
        "membership": "healing",
        "timezone": "Europe/London",
    },
    {
        "key": "samira",
        "email": f"samira.h@{SEED_EMAIL_DOMAIN}",
        "display_name": "Samira H.",
        "username": "samirahustle",
        "bio": "money used to scare me tbh. learning in public one spreadsheet at a time",
        "membership": "full_bloom",
        "timezone": "America/New_York",
    },
    {
        "key": "taylor",
        "email": f"taylor.b@{SEED_EMAIL_DOMAIN}",
        "display_name": "Taylor B.",
        "username": "taylorbsoft",
        "bio": "soft life in progress. custody weekends = my reset",
        "membership": "healing",
        "timezone": "America/Chicago",
    },
    {
        "key": "reece",
        "email": f"reece.o@{SEED_EMAIL_DOMAIN}",
        "display_name": "Reece O.",
        "username": "reeceopens",
        "bio": "starting over at 34. new city new inbox same anxious brain",
        "membership": "healing",
        "timezone": "America/Phoenix",
    },
    {
        "key": "carmen",
        "email": f"carmen.d@{SEED_EMAIL_DOMAIN}",
        "display_name": "Carmen D.",
        "username": "carmendaily",
        "bio": "i show up messy. healing circle regular. proud of that",
        "membership": "healing",
        "timezone": "America/Toronto",
    },
    {
        "key": "alexis",
        "email": f"alexis.w@{SEED_EMAIL_DOMAIN}",
        "display_name": "Alexis W.",
        "username": "alexiswrites",
        "bio": "writing guides between school runs. consistency > perfect always",
        "membership": "healing",
        "timezone": "America/Chicago",
    },
    {
        "key": "dee",
        "email": f"dee.s@{SEED_EMAIL_DOMAIN}",
        "display_name": "Dee S.",
        "username": "deesettle",
        "bio": "divorce finalized in march. still learning how to take up space",
        "membership": "healing",
        "timezone": "America/New_York",
    },
    {
        "key": "mira",
        "email": f"mira.p@{SEED_EMAIL_DOMAIN}",
        "display_name": "Mira P.",
        "username": "mirapixels",
        "bio": "brand of one. selling quiet tools for loud seasons",
        "membership": "full_bloom",
        "timezone": "Europe/Berlin",
    },
)

# Threads — intentionally imperfect typing (real phone energy).
THREADS = (
    # --- Healing ---
    {
        "forum": "healing",
        "tag": "venting",
        "author": "maya",
        "looking_for": "listening",
        "anonymous": False,
        "days_ago": 14,
        "title": "anyone else getting weirdly mad at happy couples lately",
        "body": (
            "ok not proud of this but i saw a date night reel and just closed the app like 😐\n\n"
            "im doing the work. therapy when i can afford it. showing up for my kid. "
            "but some nights the bitterness just sneaks in and idk where to put it\n\n"
            "please tell me this is a phase and not my whole personality now"
        ),
        "likes": ["jordan", "carmen", "taylor", "dee"],
        "comments": [
            {
                "author": "carmen",
                "hours_after": 2,
                "body": (
                    "girl SAME. i used to think it meant i was stuck but honestly "
                    "i think it just means my nervous system is still catching up. "
                    "youre not becoming bitter youre just noticing the gap"
                ),
                "replies": [
                    {
                        "author": "maya",
                        "hours_after": 4,
                        "body": "ok \"noticing the gap\" hits softer than calling myself mean lol thank u",
                    },
                ],
            },
            {
                "author": "dee",
                "hours_after": 6,
                "body": (
                    "phase for me too. peaked around month 8 after the split then it softened. "
                    "mute the couple content for a bit if u need. protect ur peace like its rent"
                ),
            },
            {
                "author": "taylor",
                "hours_after": 11,
                "anonymous": True,
                "body": (
                    "posting anon bc this is tender but i cried in a target parking lot "
                    "over a fathers day display once so yeah. ur not alone in the ugly feelings"
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
        "title": "first solo holiday w my kid... tips that arent pinterest please",
        "body": (
            "ex has them every other holiday. this is my first thanksgiving alone with my daughter "
            "and im spiraling about making it \"special enough\"\n\n"
            "i dont need a turkey centerpiece tutorial i need the real stuff. what actually "
            "helped ur kid feel ok when the other house felt louder"
        ),
        "likes": ["maya", "taylor", "priya", "alisha", "carmen"],
        "comments": [
            {
                "author": "taylor",
                "hours_after": 1,
                "body": (
                    "we do pajamas at like 4pm takeout and a movie weve already seen. "
                    "low pressure = she actually laughs. the pressure was for ME not her"
                ),
            },
            {
                "author": "priya",
                "hours_after": 3,
                "body": (
                    "i let my son pick one thing thats ours. for us its cinnamon rolls for dinner "
                    "which is weird but sacred and he owns it"
                ),
                "replies": [
                    {
                        "author": "dee",
                        "hours_after": 5,
                        "body": "cinnamon rolls for dinner is going on the list thank u both 😭",
                    },
                ],
            },
            {
                "author": "alisha",
                "hours_after": 8,
                "body": (
                    "also narrate less. i used to over explain why dad wasnt there and "
                    "kids mostly just need you there not a ted talk"
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
        "title": "grief anniversary tomorrow and i keep drafting texts then deleting them",
        "body": (
            "2 years since my mom. tomorrow is the day and i keep typing messages to people "
            "who already know and then deleting them\n\n"
            "dont really need advice. just company in the weird grief that doesnt look like "
            "crying on the floor anymore. sometimes its just restless and weird"
        ),
        "likes": ["maya", "carmen", "dee", "taylor"],
        "comments": [
            {
                "author": "carmen",
                "hours_after": 1,
                "body": (
                    "sitting with you from here. restless grief is still grief. "
                    "you dont owe anybody a polished version of missing her"
                ),
            },
            {
                "author": "maya",
                "hours_after": 4,
                "body": (
                    "i light a candle and put on a song she liked even if i only last like 20 sec. "
                    "tiny ritual zero performance. sending you a soft tomorrow"
                ),
                "replies": [
                    {
                        "author": "alisha",
                        "hours_after": 7,
                        "body": "candle + song. gonna try that. thank u for not rushing me",
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
        "title": "i said no to a favor that wouldve wrecked my week",
        "body": (
            "old me would’ve said yes and then resented everyone. today i just said "
            "\"i cant this week\" and didnt write a whole essay of apologies after\n\n"
            "hands were shaking ngl. still proud tho. needed somewhere to put that"
        ),
        "likes": ["jordan", "priya", "nina", "samira", "maya", "alexis"],
        "comments": [
            {
                "author": "jordan",
                "hours_after": 2,
                "body": "thats a win. screenshot this for the days you forget",
            },
            {
                "author": "samira",
                "hours_after": 5,
                "body": "shaking hands + clear boundary = growth. im clapping in my kitchen rn fr",
                "replies": [
                    {
                        "author": "taylor",
                        "hours_after": 9,
                        "body": "yall made me tear up in a good way thank u",
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
        "title": "tired of being the \"strong friend\"",
        "body": (
            "everyone comes to me. i love my people. but tonight i want someone else "
            "to hold the bag for once\n\n"
            "anon bc theyd recognize my voice. just needed to say it somewhere safe"
        ),
        "likes": ["alisha", "dee", "maya", "taylor"],
        "comments": [
            {
                "author": "alisha",
                "hours_after": 3,
                "body": (
                    "being the strong friend is lonely as hell. you get to need a soft landing too. "
                    "hope tonight gives you even like 10 quiet minutes that are just yours"
                ),
            },
            {
                "author": "dee",
                "hours_after": 6,
                "body": "heard. youre allowed to be held. full stop",
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
        "title": "anyone use a shared calendar that doesnt turn into a war zone",
        "body": (
            "looking for practical tools not the \"just communicate better\" stuff. "
            "me and my ex text and it goes sideways so fast. what apps or systems "
            "actually lowered the temperature for u"
        ),
        "likes": ["priya", "dee", "taylor"],
        "comments": [
            {
                "author": "priya",
                "hours_after": 2,
                "body": (
                    "we moved logistics to ourfamilywizard. not free but fewer 11pm fights. "
                    "anything emotional stays OUT of the app on purpose"
                ),
            },
            {
                "author": "dee",
                "hours_after": 5,
                "body": (
                    "google calendar + hard rule: only schedule/pickup notes. no commentary. "
                    "if it needs feelings it waits"
                ),
                "replies": [
                    {
                        "author": "maya",
                        "hours_after": 8,
                        "body": "the no commentary rule might save my life trying that this week",
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
        "title": "new city no friends yet... how did u rebuild community without forcing it",
        "body": (
            "moved 3 weeks ago. apt is fine. evenings feel loud-quiet if that makes sense. "
            "dont wanna join 12 things and burn out. what actually worked when u were the new person"
        ),
        "likes": ["jordan", "nina", "alexis", "carmen"],
        "comments": [
            {
                "author": "nina",
                "hours_after": 2,
                "body": (
                    "one recurring thing > five random one offs. for me it was a wednesday "
                    "writing cafe. same faces low small talk pressure"
                ),
            },
            {
                "author": "jordan",
                "hours_after": 4,
                "body": (
                    "also parallel play energy. library gym coworking. ur around people "
                    "without performing friendship on day one"
                ),
                "replies": [
                    {
                        "author": "reece",
                        "hours_after": 7,
                        "body": "parallel play is exactly what i needed thank u",
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
        "title": "posted 4x this week and my brain still says im inconsistent",
        "body": (
            "logically i know 4 posts is better than the months i vanished. "
            "emotionally im comparing myself to people who batch 30 reels before breakfast\n\n"
            "anyone else fighting the \"if its not daily it doesnt count\" lie"
        ),
        "likes": ["alexis", "jordan", "mira", "priya", "samira"],
        "comments": [
            {
                "author": "alexis",
                "hours_after": 1,
                "body": (
                    "daily is a strategy not a moral law lol. 4 thoughtful posts beat 7 empty ones. "
                    "ur building a habit not failing a streak app"
                ),
            },
            {
                "author": "mira",
                "hours_after": 3,
                "body": (
                    "i batch on sundays when i can and when i cant i just do 2 solid posts. "
                    "the algorithm is not ur landlord"
                ),
                "replies": [
                    {
                        "author": "nina",
                        "hours_after": 6,
                        "body": "\"algorithm is not ur landlord\" im putting that on my mood board 💀",
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
        "title": "starting a tiny offer w almost no audience... what would u sell first",
        "body": (
            "i have a skill (resume + linkedin makeovers) and like 400 followers who barely "
            "know i exist online. tempted to build a huge course. also tempted to freeze\n\n"
            "if u started from near zero what was ur first paid thing that wasnt embarrassing"
        ),
        "likes": ["jordan", "nina", "alexis", "samira"],
        "comments": [
            {
                "author": "jordan",
                "hours_after": 2,
                "body": (
                    "i sold 1:1 before any product. like five clients taught me what people "
                    "actually pay for. course came later from their repeated questions"
                ),
            },
            {
                "author": "alexis",
                "hours_after": 5,
                "body": (
                    "$27 pdf that answered one painful question. ugly canva. sold 11. "
                    "then i improved it. starting ugly is allowed"
                ),
                "replies": [
                    {
                        "author": "reece",
                        "hours_after": 9,
                        "body": "ugly canva courage unlocked. drafting a mini offer this weekend",
                    },
                ],
            },
            {
                "author": "samira",
                "hours_after": 12,
                "body": "also dm the quiet engagers. warm > cold. ur 400 arent zero",
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
        "title": "first $100 into investing... what did u actually open",
        "body": (
            "not looking for stock tips. looking for \"i was scared and i opened X and survived\"\n\n"
            "i finally have $100 that isnt rent or groceries money and my brain wants to "
            "keep it in checking forever \"just in case\""
        ),
        "likes": ["priya", "jordan", "mira", "maya", "alexis"],
        "comments": [
            {
                "author": "priya",
                "hours_after": 2,
                "body": (
                    "started with a basic brokerage + a target date fund. boring on purpose. "
                    "the win was separating emergency money from investing so i stopped raiding it"
                ),
            },
            {
                "author": "mira",
                "hours_after": 4,
                "body": (
                    "automate like $25 transfers so u dont negotiate with yourself every week. "
                    "small and boring beats heroic then abandoned"
                ),
                "replies": [
                    {
                        "author": "samira",
                        "hours_after": 7,
                        "body": "ooo automating the decision is smart. setting $25 for friday thank u",
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
        "title": "sold my first guide while my kid was glued to a cartoon im screaming quietly",
        "body": (
            "its not six figures. its ONE sale. but i built it between nap times and "
            "self doubt for months\n\n"
            "needed a room that gets why this feels enormous"
        ),
        "likes": ["nina", "jordan", "samira", "priya", "mira", "reece", "maya"],
        "comments": [
            {
                "author": "nina",
                "hours_after": 1,
                "body": "SCREAMING WITH U. first sale energy is unmatched. go celebrate something tiny tonight",
            },
            {
                "author": "jordan",
                "hours_after": 3,
                "body": "proof u can finish. thats the hard part. congrats for real",
                "replies": [
                    {
                        "author": "alexis",
                        "hours_after": 5,
                        "body": "we got ice cream. cartoon still playing. perfect chaos lol",
                    },
                ],
            },
            {
                "author": "priya",
                "hours_after": 8,
                "body": "put the screenshot somewhere ull see it on hard days",
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
        "title": "do u write captions before filming or after (and regret either way)",
        "body": (
            "i film \"vibes\" then stare at a blank caption box for like 40 min. "
            "or i write a perfect caption and then hate every take. whats ur order "
            "when ur short on time"
        ),
        "likes": ["nina", "alexis", "jordan"],
        "comments": [
            {
                "author": "nina",
                "hours_after": 2,
                "body": (
                    "hook line first even if its ugly. film to that line. polish caption after. "
                    "stops me from collecting random clips with no point"
                ),
            },
            {
                "author": "alexis",
                "hours_after": 5,
                "body": (
                    "voice note the idea while walking then transcribe later. my best captions "
                    "sound like how i talk not how i \"should\" write"
                ),
                "replies": [
                    {
                        "author": "mira",
                        "hours_after": 8,
                        "body": "voice notes while walking = genius trying that tmw",
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
        "title": "raising my rate next month and my stomach already hates me",
        "body": (
            "been undercharging \"to be nice.\" clients are happy. my bank account is not. "
            "bumping rates for new work next month and i keep rehearsing apologies nobody asked for\n\n"
            "if uve done this what did u say in the email that didnt sound desperate"
        ),
        "likes": ["samira", "mira", "priya", "alexis", "nina"],
        "comments": [
            {
                "author": "samira",
                "hours_after": 2,
                "body": (
                    "keep it short: \"my rates update on [date]. happy to lock current pricing "
                    "if you book before then.\" no novel needed"
                ),
            },
            {
                "author": "mira",
                "hours_after": 4,
                "body": (
                    "u dont need to justify the raise with ur whole life story. clarity is kindness. "
                    "the ones who value u stay. the rest were never priced right anyway"
                ),
                "replies": [
                    {
                        "author": "jordan",
                        "hours_after": 6,
                        "body": "drafting the short version now. hands still shaky. doing it anyway",
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
        "title": "hit $1k in digital product sales this month (co-parenting on hard mode)",
        "body": (
            "not flexing at anyone more like pinning this so i remember on the weeks "
            "i feel behind. school emails schedule swaps and still shipping\n\n"
            "if ur in the messy middle keep going. quiet progress counts"
        ),
        "likes": ["samira", "nina", "alexis", "mira", "jordan", "maya", "reece"],
        "comments": [
            {
                "author": "samira",
                "hours_after": 1,
                "body": "THIS. quiet progress is still an empire brick. congrats priya 👏",
            },
            {
                "author": "maya",
                "hours_after": 3,
                "body": "needed this today. thank u for sharing the middle not just the highlight",
                "replies": [
                    {
                        "author": "priya",
                        "hours_after": 5,
                        "body": "the middle is where we live lol. glad it landed",
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
        "title": "deleted a half built offer and it felt like failure + relief",
        "body": (
            "spent weeks on something that wasnt me. scrapped it this morning. "
            "part of me thinks i wasted time. part of me feels lighter??\n\n"
            "anyone else have to kill a project to make room for the right one"
        ),
        "likes": ["reece", "jordan", "alexis", "mira"],
        "comments": [
            {
                "author": "reece",
                "hours_after": 1,
                "body": (
                    "killing a wrong offer is still progress. u learned what u dont wanna sell. "
                    "thats expensive research if u paid someone else for it"
                ),
            },
            {
                "author": "jordan",
                "hours_after": 3,
                "body": "relief is data. listen to it",
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


def _seed_user_ids() -> list[int]:
    return [
        uid for (uid,) in
        db.session.query(User.id)
        .filter(User.email.like(f"%@{SEED_EMAIL_DOMAIN}"))
        .all()
    ]


def _wipe_seed_threads(user_ids: list[int]) -> None:
    """Delete posts (and dependents) authored by seed members. No commit."""
    if not user_ids:
        return
    from ..models import ContentReport, Notification

    post_ids = [
        pid for (pid,) in
        db.session.query(ForumPost.id).filter(ForumPost.user_id.in_(user_ids)).all()
    ]
    if not post_ids:
        return
    comment_ids = [
        cid for (cid,) in
        db.session.query(ForumComment.id)
        .filter(ForumComment.post_id.in_(post_ids))
        .all()
    ]
    Notification.query.filter(Notification.post_id.in_(post_ids)).delete(
        synchronize_session=False
    )
    ContentReport.query.filter(
        ContentReport.target_type == "post",
        ContentReport.target_id.in_(post_ids),
    ).delete(synchronize_session=False)
    if comment_ids:
        ContentReport.query.filter(
            ContentReport.target_type == "comment",
            ContentReport.target_id.in_(comment_ids),
        ).delete(synchronize_session=False)
        ForumCommentLike.query.filter(
            ForumCommentLike.comment_id.in_(comment_ids)
        ).delete(synchronize_session=False)
        ForumComment.query.filter(ForumComment.id.in_(comment_ids)).update(
            {ForumComment.parent_id: None}, synchronize_session=False
        )
        ForumComment.query.filter(ForumComment.id.in_(comment_ids)).delete(
            synchronize_session=False
        )
    ForumPostLike.query.filter(ForumPostLike.post_id.in_(post_ids)).delete(
        synchronize_session=False
    )
    ForumPost.query.filter(ForumPost.id.in_(post_ids)).delete(synchronize_session=False)


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


def _load_members_by_key() -> dict[str, User]:
    by_key: dict[str, User] = {}
    for row in MEMBERS:
        user = User.query.filter_by(email=row["email"]).first()
        if user is not None:
            by_key[row["key"]] = user
    return by_key


def _create_threads(by_key: dict[str, User]) -> tuple[int, int]:
    cats = {c.slug: c for c in ForumCategory.query.all()}
    tags_by = {slug: {t.slug: t for t in cat.tags} for slug, cat in cats.items()}
    now = utcnow()
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

    return posts_n, comments_n


def seed_community_buzz() -> dict[str, int]:
    """Create launch buzz members + threads. Returns counts added."""
    from .settings import get_setting, set_setting

    cats = {c.slug: c for c in ForumCategory.query.all()}
    if "healing" not in cats or "building" not in cats:
        return {"members": 0, "posts": 0, "comments": 0, "skipped": 1}

    current_copy = (get_setting(COPY_SETTING_KEY) or "").strip()
    need_fresh_copy = current_copy != COPY_VERSION

    if _seed_emails_exist():
        synced = _sync_existing_members()
        if not need_fresh_copy:
            return {
                "members": 0, "posts": 0, "comments": 0,
                "skipped": 1, "synced": synced,
            }
        by_key = _load_members_by_key()
        _wipe_seed_threads(_seed_user_ids())
        db.session.flush()
        posts_n, comments_n = _create_threads(by_key)
        set_setting(COPY_SETTING_KEY, COPY_VERSION)
        db.session.flush()
        return {
            "members": 0,
            "posts": posts_n,
            "comments": comments_n,
            "skipped": 0,
            "synced": synced,
            "refreshed": 1,
        }

    now = utcnow()
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
    for row in MEMBERS:
        if row["key"] not in by_key:
            existing = User.query.filter_by(email=row["email"]).first()
            if existing is not None:
                by_key[row["key"]] = existing

    posts_n, comments_n = _create_threads(by_key)
    set_setting(COPY_SETTING_KEY, COPY_VERSION)
    db.session.flush()
    return {
        "members": len(by_key),
        "posts": posts_n,
        "comments": comments_n,
        "skipped": 0,
    }
