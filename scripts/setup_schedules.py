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
    # (team_id, slack_channel, open_cron, preread_cron, callsummary_cron, timezone)
    # e.g. standup at 10am Mon–Fri: open 9:30, pre-read 9:55, call summary 10:30
    ("core", "#core-standup", "30 9 * * 1-5", "55 9 * * 1-5", "30 10 * * 1-5", "Asia/Kolkata"),
]
CONCIERGE = [
    # (user_id(email), task_name, instruction, cron, timezone)
    ("you@axelerant.com", "morning-brief",
     "Give me my open action items and anything due today, scoped to me.",
     "0 8 * * 1-5", "Asia/Kolkata"),
]
# Sprint reports roll out to EVERY engagement automatically (Bott discovers all Jira
# boards). Set a cadence (typically the sprint-end day/time) and a timezone; channels are
# resolved per engagement via Memra at run time. Set to None to skip.
SPRINT_REPORTS = ("0 17 * * 5", "Asia/Kolkata")  # Fridays 5pm; or None
# -----------------------------------------------------------------------------------


def main() -> None:
    db = build_db()
    for eng, ch, cron, tz in DELIVERY:
        scheduling.create_delivery_synthesis(db, engagement_id=eng, channel=ch, cron=cron, timezone=tz)
        print(f"delivery-synthesis: {eng} → {ch} @ {cron} ({tz})")
    for team, ch, open_cron, preread_cron, callsummary_cron, tz in DSM:
        scheduling.create_dsm_open(db, team_id=team, channel=ch, cron=open_cron, timezone=tz)
        scheduling.create_dsm_preread(db, team_id=team, channel=ch, cron=preread_cron, timezone=tz)
        scheduling.create_dsm_callsummary(db, team_id=team, channel=ch, cron=callsummary_cron, timezone=tz)
        print(f"dsm: {team} → {ch} open@{open_cron} preread@{preread_cron} callsummary@{callsummary_cron} ({tz})")
    for uid, name, instr, cron, tz in CONCIERGE:
        scheduling.create_recurring_task(db, user_id=uid, task_name=name, instruction=instr, cron=cron, timezone=tz)
        print(f"concierge: {uid}/{name} @ {cron} ({tz})")
    if SPRINT_REPORTS:
        from bott.shared import config

        cron, tz = SPRINT_REPORTS
        if config.jira_configured():
            keys = scheduling.schedule_sprint_reports_for_all(db, cron=cron, timezone=tz)
            print(f"sprint-report: {len(keys)} engagement(s) → {', '.join(keys)} @ {cron} ({tz})")
        else:
            print("sprint-report: skipped (Jira not configured — set JIRA_BASE_URL/EMAIL/API_TOKEN)")
    print("\nDone. Schedules persisted; the running app's scheduler will fire them.")


if __name__ == "__main__":
    main()
