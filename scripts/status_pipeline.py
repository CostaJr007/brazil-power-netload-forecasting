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
    """Lê a tarefa agendada via PowerShell; devolve None fora do Windows ou se não existir."""
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
    # Toda execução normal grava latest.json, mesmo sem nada a fazer. Mais velho que 2 ticks = algo parou.
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(latest["completed_at"])).total_seconds() / 60
    stale = age > 2 * config["scheduler_minutes"] + 5
    scheduler = scheduler_info()
    alerts = []
    if stale:
        alerts.append(f"Último relatório tem {age:.0f} min: o agendamento pode ter parado ou execuções estão caindo.")
    if scheduler and scheduler.get("last_result") not in (0, 267009, 267011):
        # 267009 = em execução; 267011 = ainda não executou.
        alerts.append(f"Agendador: última execução terminou com código {scheduler['last_result']} (0 = sucesso).")
    status = latest["status"] if not alerts else "attention"
    result = {"checked_at": utcnow(), "last_run": latest["run_id"], "last_run_status": latest["status"],
              "status": status, "minutes_since_last_run": round(age, 1), "alerts": alerts, "scheduler": scheduler,
              "errors": latest["errors"], "tasks": tasks, "datasets": list(datasets.values()),
              "note": "Contagens são por snapshot de recurso, não energia total nem deduplicação entre produtos/fontes.",
              "blocked_sources": latest["blocked_sources"]}
    atomic_json(ROOT / "docs/inventory/pipeline_status.json", result)
    lines = ["# Estado do pipeline", "",
             f"Verificado: {result['checked_at']}; execução: {result['last_run']} ({latest['status']}, há {age:.0f} min); status geral: **{status}**.", ""]
    if scheduler:
        lines += [f"Agendador: última execução {scheduler['last_run']}, código {scheduler['last_result']}; próxima {scheduler['next_run']}.", ""]
    if alerts:
        lines += ["**Alertas:**", ""] + [f"- {a}" for a in alerts] + [""]
    lines += ["| Conjunto | Snapshots de recursos | Linhas válidas | Rejeitadas |", "|---|---:|---:|---:|"]
    for row in datasets.values():
        lines.append(f"| {row['dataset']} | {row['snapshots']} | {row['valid_rows']} | {row['rejected_rows']} |")
    lines += ["", "As contagens não devem ser somadas como se fossem uma única tabela ou medidas de energia. Produtos e períodos podem se sobrepor.", "",
              "Fontes bloqueadas:", ""] + [f"- **{k}**: {v}" for k, v in latest["blocked_sources"].items()]
    (ROOT / "docs/inventory/pipeline_status.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "alerts": alerts, "datasets": len(datasets),
                      "valid_rows_across_resources": sum(d["valid_rows"] for d in datasets.values()),
                      "errors": latest["errors"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
