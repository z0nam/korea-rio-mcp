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
