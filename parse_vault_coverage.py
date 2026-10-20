"""Summarize Telegram Vault statement and branch gaps from Coverage.py JSON."""
import json
import os
import sys


def analyze_vault_coverage(json_path="coverage.json"):
    if not os.path.isfile(json_path):
        print(f"Error: {json_path} not found. Run 'coverage json' first.", file=sys.stderr)
        return 1
    try:
        with open(json_path, encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, ValueError) as exc:
        print(f"Error: could not read coverage JSON ({type(exc).__name__}).", file=sys.stderr)
        return 1

    files = data.get("files", {})
    matches = [key for key in files if os.path.basename(key.replace("\\", "/")) == "telegram_vault.py"]
    if len(matches) != 1:
        print(f"Error: expected one telegram_vault.py entry, found {len(matches)}.", file=sys.stderr)
        return 1

    key = matches[0]
    entry = files[key]
    summary = entry.get("summary", {})
    statements = summary.get("num_statements", 0)
    covered = summary.get("covered_lines", 0)
    branches = summary.get("num_branches", 0)
    covered_branches = summary.get("covered_branches", 0)
    missing_lines = sorted(entry.get("missing_lines", []))
    missing_branches = sorted(entry.get("missing_branches", []))
    print(f"Telegram Vault coverage: {key}")
    print(f"Statements: {covered}/{statements} ({100 * covered / statements:.2f}%)" if statements else "Statements: unavailable")
    print(f"Branches: {covered_branches}/{branches} ({100 * covered_branches / branches:.2f}%)" if branches else "Branches: unavailable (branch tracking may be disabled)")
    print(f"Combined coverage: {summary.get('percent_covered_display', summary.get('percent_covered', 'unknown'))}%")
    print(f"Missing statements ({len(missing_lines)}): {', '.join(map(str, missing_lines)) or 'none'}")
    print(f"Missing branch transitions ({len(missing_branches)}):")
    for source, destination in missing_branches:
        print(f"  {source} -> {destination}")
    if not missing_branches:
        print("  none")
    return 0


if __name__ == "__main__":
    sys.exit(analyze_vault_coverage(sys.argv[1] if len(sys.argv) > 1 else "coverage.json"))
