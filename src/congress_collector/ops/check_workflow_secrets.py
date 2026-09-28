"""Fails if any workflow triggered by `pull_request` references a secret, or
if `pull_request_target` is used at all.

The real risk this guards against: a fork's pull request can modify a
`.github/workflows/*.yml` file, and for `pull_request`-triggered workflows
GitHub runs the fork's own modified copy of that file -- so if a workflow
that triggers on `pull_request` ever starts referencing `secrets.*`, a
malicious PR could add a step that exfiltrates it (R2, Supabase, and
Telegram credentials here, all of which cost money or grant write access if
leaked). This turns that into a red, automated CI failure instead of
something only a careful manual review of the diff would catch.
`pull_request_target` is flagged unconditionally, with or without a secret
reference: it runs with the base repo's secrets while checking out the
fork's code, which this repo has no use for and should never gain by
accident.

Run by ci.yml on every push and pull_request -- deliberately needs no
secrets itself, so it always runs, including on a fork's PR.
"""

import sys
from pathlib import Path

import yaml

WORKFLOWS_DIR = Path(__file__).parents[3] / ".github" / "workflows"


def check_content(name: str, text: str) -> list[str]:
    """Problem descriptions for one workflow file's name and raw YAML text,
    or an empty list if it's fine."""
    workflow = yaml.safe_load(text)
    # PyYAML (1.1 rules) parses a bare `on:` key as the boolean True, not
    # the string "on" -- confirmed against this repo's own ci.yml.
    on = workflow.get("on", workflow.get(True, {}))
    if isinstance(on, dict):
        triggers = set(on)
    elif isinstance(on, str):
        triggers = {on}
    else:
        triggers = set(on or [])

    problems = []
    if "pull_request_target" in triggers:
        problems.append(
            f"{name}: uses pull_request_target, which runs with base-repo secrets against fork code"
        )
    if "pull_request" in triggers and "secrets." in text:
        problems.append(f"{name}: triggered by pull_request and references a secret")
    return problems


def main() -> int:
    paths = sorted(WORKFLOWS_DIR.glob("*.yml"))
    problems = [p for path in paths for p in check_content(path.name, path.read_text())]

    if problems:
        print("Workflow secret-exposure check failed:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"Workflow secret-exposure check passed ({len(paths)} workflow files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
