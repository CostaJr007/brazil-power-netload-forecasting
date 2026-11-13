"""Shows pipeline status and results without collecting or transforming files.

Besides the latest report, it checks two things the report alone cannot show:
- whether the report is LATE (a run that dies midway writes no report);
- the Windows Task Scheduler result (LastTaskResult).
"""
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timezone

from acquire import DATA_DIR, ROOT, atomic_json, utcnow


def scheduler_info(name="Energy-Data-Pipeline"):
    """Read the scheduled task via PowerShell; returns None outside Windows or if it does not exist."""
    if os.name != "nt":
        return None
    command = (f"$i = Get-ScheduledTaskInfo -TaskName '{name}' -ErrorAction Stop; "
               "[pscustomobject]@{last_run=$i.LastRunTime.ToString('o'); last_result=$i.LastTaskResult; "
               "next_run=$i.NextRunTime.ToString('o')} | ConvertTo-Json -Compress")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                capture_output=True, text=True, timeout=30)
        return json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else None
    except Exception:
        return None


def main():
    root = DATA_DIR
    config = json.loads((ROOT / "configs/pipeline.json").read_text(encoding="utf-8"))
    latest = json.loads((root / "runs/latest.json").read_text(encoding="utf-8"))
    current = json.loads((root / "silver/current.json").read_text(encoding="utf-8"))
    datasets = {}
    for snapshot in current["snapshots"]:
        name = snapshot["source_manifest"]["dataset"]
        row = datasets.setdefault(name, {"dataset": name, "snapshots": 0, "valid_rows": 0, "rejected_rows": 0})
        row["snapshots"] += 1
        row["valid_rows"] += snapshot["valid_rows"]
        row["rejected_rows"] += snapshot["rejected_rows"]
    con = sqlite3.connect(f"file:{(root / 'pipeline.sqlite').as_posix()}?mode=ro", uri=True)
    try:
        tasks = [{"task": name, "last_success_utc": value} for name, value in con.execute("SELECT name,last_success FROM tasks ORDER BY name")]
    finally:
        con.close()
    # Every normal run writes latest.json, even with nothing to do. Older than 2 ticks = something stopped.
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(latest["completed_at"])).total_seconds() / 60
    stale = age > 2 * config["scheduler_minutes"] + 5
    scheduler = scheduler_info()
    alerts = []
    if stale:
        alerts.append(f"Latest report is {age:.0f} min old: the schedule may have stopped or runs are crashing.")
    if scheduler and scheduler.get("last_result") not in (0, 267009, 267011):
        # 267009 = running; 267011 = has not run yet.
        alerts.append(f"Task Scheduler: last run ended with code {scheduler['last_result']} (0 = success).")
    status = latest["status"] if not alerts else "attention"
    result = {"checked_at": utcnow(), "last_run": latest["run_id"], "last_run_status": latest["status"],
              "status": status, "minutes_since_last_run": round(age, 1), "alerts": alerts, "scheduler": scheduler,
              "errors": latest["errors"], "tasks": tasks, "datasets": list(datasets.values()),
              "note": "Counts are per resource snapshot, not total energy and not deduplicated across products/sources.",
              "blocked_sources": latest["blocked_sources"]}
    atomic_json(ROOT / "docs/inventory/pipeline_status.json", result)
    lines = ["# Pipeline status", "",
             f"Checked: {result['checked_at']}; run: {result['last_run']} ({latest['status']}, {age:.0f} min ago); overall status: **{status}**.", ""]
    if scheduler:
        lines += [f"Task Scheduler: last run {scheduler['last_run']}, code {scheduler['last_result']}; next {scheduler['next_run']}.", ""]
    if alerts:
        lines += ["**Alertas:**", ""] + [f"- {a}" for a in alerts] + [""]
    lines += ["| Dataset | Resource snapshots | Valid rows | Rejected |", "|---|---:|---:|---:|"]
    for row in datasets.values():
        lines.append(f"| {row['dataset']} | {row['snapshots']} | {row['valid_rows']} | {row['rejected_rows']} |")
    lines += ["", "Counts must not be summed as if they were one table or energy measures. Products and periods may overlap.", "",
              "Blocked sources:", ""] + [f"- **{k}**: {v}" for k, v in latest["blocked_sources"].items()]
    (ROOT / "docs/inventory/pipeline_status.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "alerts": alerts, "datasets": len(datasets),
                      "valid_rows_across_resources": sum(d["valid_rows"] for d in datasets.values()),
                      "errors": latest["errors"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
