import json
import shutil
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]


def excerpt(source, target, limit):
    lines = source.read_text(encoding="utf-8").splitlines()
    target.write_text("\n".join(lines[:limit]) + "\n", encoding="utf-8")
    return len(lines)


def main():
    latest = json.loads((ROOT / "runtime" / "latest-verification.json").read_text())
    source = Path(latest["root"])
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    counts = {}
    for name, path, limit in (
        ("client-http", source / "client-logs" / "http.jsonl", 36),
        ("backend-http", source / "server-1" / "http.jsonl", 100),
        ("callback-http", source / "client-logs" / "callback-http.jsonl", 6),
        ("tools", source / "server-1" / "tools.jsonl", 20),
    ):
        counts[name] = excerpt(path, docs / f"representative-{name}.jsonl", limit)
    result = ROOT / "runtime" / "test-results.xml"
    shutil.copyfile(result, docs / "test-results.xml")
    suite = ElementTree.parse(result).getroot().find("testsuite")
    assert suite.get("failures") == "0" and suite.get("errors") == "0"
    summary = {"tests": int(suite.get("tests")), "failures": 0, "errors": 0,
               "seconds": float(suite.get("time")), "timestamp": suite.get("timestamp"),
               "verification_directory": str(source), "server_urls": latest["urls"], "log_record_counts": counts}
    (docs / "test-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    public = ROOT / "runtime" / "public-verification.json"
    if public.exists():
        shutil.copyfile(public, docs / "public-verification.json")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
