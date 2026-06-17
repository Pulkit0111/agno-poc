"""Admin helper: register the POC's scheduled flows on the running AgentOS scheduler.

Each schedule embeds user_id/session_id in its payload so scheduled runs stay scoped.
Edit the examples below for your engagements/teams/users, then run:

    python scripts/setup_schedules.py

Schedules persist in the DB; the app's scheduler poller (scheduler=True) fires them.
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from bott.shared.db import build_db  # noqa: E402
from bott.skills import scheduling  # noqa: E402

# ---- edit these for your workspace ------------------------------------------------
DELIVERY = [
    # (engagement_id, slack_channel, cron, timezone)
    ("acme-portal", "#acme-portal", "0 9 * * 1", "Asia/Kolkata"),  # Mondays 9am
]
DSM = [
    # (team_id, slack_channel, precall_cron, postcall_cron, timezone)
    ("core", "#core-standup", "55 9 * * 1-5", "30 10 * * 1-5", "Asia/Kolkata"),
]
CONCIERGE = [
    # (user_id(email), task_name, instruction, cron, timezone)
    ("you@axelerant.com", "morning-brief",
     "Give me my open action items and anything due today, scoped to me.",
     "0 8 * * 1-5", "Asia/Kolkata"),
]
# -----------------------------------------------------------------------------------


def main() -> None:
    db = build_db()
    for eng, ch, cron, tz in DELIVERY:
        scheduling.create_delivery_synthesis(db, engagement_id=eng, channel=ch, cron=cron, timezone=tz)
        print(f"delivery-synthesis: {eng} → {ch} @ {cron} ({tz})")
    for team, ch, pre, post, tz in DSM:
        scheduling.create_dsm_precall(db, team_id=team, channel=ch, cron=pre, timezone=tz)
        scheduling.create_dsm_postcall(db, team_id=team, channel=ch, cron=post, timezone=tz)
        print(f"dsm: {team} → {ch} pre@{pre} post@{post} ({tz})")
    for uid, name, instr, cron, tz in CONCIERGE:
        scheduling.create_recurring_task(db, user_id=uid, task_name=name, instruction=instr, cron=cron, timezone=tz)
        print(f"concierge: {uid}/{name} @ {cron} ({tz})")
    print("\nDone. Schedules persisted; the running app's scheduler will fire them.")


if __name__ == "__main__":
    main()
