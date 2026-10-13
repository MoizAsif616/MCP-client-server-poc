"""Export passed ngrok test reports and excerpts of their actual application logs."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def excerpt(data, target, limit=70):
    selected = data[:limit]
    # Include actual refresh exchanges that occur after the initial sign-in.
    refresh = [index for index, row in enumerate(data)
               if isinstance(row.get("body"), str) and "grant_type=refresh_token" in row["body"]]
    indices = set(range(min(limit, len(data))))
    for index in refresh[:2]:
        indices.update(range(index, min(index + 2, len(data))))
    selected = [data[index] for index in sorted(indices)]
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in selected), encoding="utf-8")
    return len(data)


def main():
    latest = json.loads((ROOT / "runtime" / "latest-ngrok-verification.json").read_text())
    source = Path(latest["root"])
    docs = ROOT / "docs"
    report = ROOT / "runtime" / "ngrok-test-results.xml"
    suite = ElementTree.parse(report).getroot().find("testsuite")
    assert suite.get("failures") == "0" and suite.get("errors") == "0" and suite.get("skipped") == "0"
    client = rows(source / "client-logs" / "http.jsonl")
    started = client[0]["timestamp"]
    backend = [row for row in rows(Path(latest["backend_logs"]) / "http.jsonl") if row["timestamp"] >= started]
    tools = [row for row in rows(Path(latest["backend_logs"]) / "tools.jsonl") if row["timestamp"] >= started]
    counts = {}
    for name, data, limit in (("client-http", client, 70), ("backend-http", backend, 100),
                              ("callback-http", rows(source / "client-logs" / "callback-http.jsonl"), 8),
                              ("tools", tools, 40)):
        counts[name] = excerpt(data, docs / f"ngrok-representative-{name}.jsonl", limit)
    excerpt(rows(source / "audit-client.jsonl"), docs / "ngrok-audit-client.jsonl")
    shutil.copyfile(report, docs / "ngrok-test-results.xml")
    lifecycle = json.loads((ROOT / "runtime" / "ngrok-lifecycle.json").read_text())
    assert all(lifecycle["checks"].values())
    shutil.copyfile(ROOT / "runtime" / "ngrok-lifecycle.json", docs / "ngrok-lifecycle.json")
    summary = {"verified_at": datetime.now(timezone.utc).isoformat(), "public_url": latest["public_url"],
               "mcp_url": latest["public_url"] + "/mcp", "tests": int(suite.get("tests")),
               "failures": 0, "errors": 0, "skipped": 0, "seconds": float(suite.get("time")),
               "timestamp": suite.get("timestamp"), "verification_directory": str(source),
               "log_record_counts": counts, "lifecycle_checks": lifecycle["checks"],
               "claude_ai_live_integration": "Prepared for user; not performed"}
    (docs / "ngrok-test-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
