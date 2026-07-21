"""Documented standard parameters for event-effect estimation.

These were hard-coded Jeju constants in 26p17 ``compute_assumptions.py``. Here
they are *defaults the caller can override*, with the source/rationale noted so
a user in another region can supply their own values rather than inheriting
Jeju assumptions silently.
"""

# Share of an event's outside visitors that came *because of* the event
# (induced trips). Drives the stay-spending base. 26p17 used 0.65 for festivals
# as a conservative standard absent a satisfaction survey.
DEFAULT_PURPOSE_WEIGHT = 0.65

# Standard per-capita on-site spending (KRW) for an outside visitor, used when
# no survey measured it. 26p17 festival/performance standard value.
DEFAULT_PER_CAPITA_WON = 150_000

# Event-site consumption sector (BOK medium classification). 80 = 스포츠·오락
# (performance/experience-led events). Override per event character:
#   52 도소매 (sales/expo-led), 58 음식점·숙박 (food-led).
DEFAULT_EVENT_SITE_SECTOR = "80"

# Even monthly weighting for stay-spending unit cost when seasonality is unknown.
# NOTE: 26p17 flagged that KTO unit costs are summer/autumn averages; applying
# them flat to off-season events can overstate by ~10-20%. Pass an explicit
# monthly_weight to correct.
DEFAULT_MONTHLY_WEIGHT = {"jul": 0.25, "aug": 0.25, "sep": 0.25, "oct": 0.25}

# Per-event-type parameter presets for the participant channel. A visitor
# group inherits from its event type's preset, and each key can still be
# overridden per group (see effects.visitor_group_effects).
EVENT_TYPE_PRESETS = {
    # 26p17 festival standard — identical to the module DEFAULT_* constants.
    "festival": {
        "profile": "jeju_domestic_leisure",
        "purpose_weight": DEFAULT_PURPOSE_WEIGHT,
        "per_capita_won": DEFAULT_PER_CAPITA_WON,
        "event_site_sector": DEFAULT_EVENT_SITE_SECTOR,
    },
    # MICE/국제행사 (forum, convention): participants travel for the event
    # itself → purpose_weight 1.0. On-site consumption is usually paid out of
    # the organizer budget (catering, venue) already counted in the policy
    # channel, so per_capita_won defaults to None (site channel off) to avoid
    # double counting — pass a surveyed value to turn it on.
    "forum_mice": {
        "profile": "jeju_domestic_business",
        "purpose_weight": 1.0,
        "per_capita_won": None,
        "event_site_sector": "58",  # 음식점·숙박 if a site value is supplied
    },
}
