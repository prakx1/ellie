"""Confirmed, oldest-first historical capture using the normal job pipeline."""

from .capture import discover_project, plan_jobs, process_job
from .redact import redact


def backfill(service, project: str, *, since: str | None = None, limit: int | None = None,
             agent: str | None = None, yes: bool = False, input_fn=None, output=None) -> int:
    import sys
    input_fn = input_fn or input
    output = output or sys.stdout
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    jobs, errors = plan_jobs(service.store, project, since=since or service.config["backfill_default_since"], source="backfill", agent=agent)
    sessions = {s.id: s for s in discover_project(service.store, project, agent=agent).sessions}
    jobs.sort(key=lambda job: (sessions[job["session_id"]].started, job["session_id"]))
    if limit is not None:
        jobs = jobs[:limit]
    if not jobs:
        print("No uncaptured historical sessions.", file=output)
        for error in errors:
            print("ellie: " + error, file=output)
        return int(bool(errors))
    runs = 0
    for job in jobs:
        session = sessions[job["session_id"]]
        runs += session.user_messages >= 2 or bool(session.history_base)
        preview = " ".join(redact(session.first_user_message).split())[:60]
        print(f"{session.started.isoformat()}  {session.agent}  {session.user_messages} user messages  {session.id}  {preview}", file=output)
    print(f"{runs} extraction runs on your codex/claude plan.", file=output)
    if not yes:
        try:
            answer = input_fn("Capture these sessions? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in {"y", "yes"}:
            print("Cancelled.", file=output)
            return 0
    failed = bool(errors)
    for job in jobs:
        job["source"] = "backfill"
        if service.store.read_pending(job["run_id"]):
            service.store.update_pending(job["run_id"], lambda data: data.update({"source": "backfill", "session_id": job["session_id"]}))
        else:
            service.store.write_pending(job["run_id"], job)
        result = process_job(service.store, job["run_id"])
        print(result.get("summary", "ellie: " + result.get("error", result["capture"])), file=output)
        failed |= result["capture"] == "failed"
    for error in errors:
        print("ellie: " + error, file=output)
    return int(failed)
