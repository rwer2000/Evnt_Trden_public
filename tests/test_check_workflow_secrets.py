from congress_collector.ops.check_workflow_secrets import check_content


def test_pull_request_triggered_workflow_without_secrets_is_fine() -> None:
    text = """
name: ci
on:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: pytest
"""
    assert check_content("ci.yml", text) == []


def test_pull_request_triggered_workflow_referencing_a_secret_is_flagged() -> None:
    text = """
name: ci
on:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
        env:
          TOKEN: ${{ secrets.R2_ACCESS_KEY_ID }}
"""
    problems = check_content("ci.yml", text)
    assert len(problems) == 1
    assert "secret" in problems[0]


def test_workflow_dispatch_with_secrets_is_fine() -> None:
    text = """
name: collect
on:
  workflow_dispatch:
jobs:
  collect:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
        env:
          TOKEN: ${{ secrets.R2_ACCESS_KEY_ID }}
"""
    assert check_content("collect.yml", text) == []


def test_pull_request_target_is_always_flagged_even_without_secrets() -> None:
    text = """
name: sketchy
on:
  pull_request_target:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""
    problems = check_content("sketchy.yml", text)
    assert len(problems) == 1
    assert "pull_request_target" in problems[0]


def test_multiple_triggers_including_pull_request_and_secrets_is_flagged() -> None:
    text = """
name: mixed
on:
  push:
  pull_request:
  schedule:
    - cron: "0 3 * * 0"
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: echo ${{ secrets.TELEGRAM_BOT_TOKEN }}
"""
    problems = check_content("mixed.yml", text)
    assert len(problems) == 1
