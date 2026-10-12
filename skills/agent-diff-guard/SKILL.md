---
name: agent-diff-guard
description: Self-check your own code changes for shortcuts before saying a coding task is done. Use whenever you are about to report that tests pass, a bug is fixed, or a feature is complete in a Python git repository, and whenever you changed tests, CI config, or lint/type/coverage settings.
---

# Self-check with agent-diff-guard

Before you tell the user a coding task is complete, run `adg` on your changes and deal
with every finding. A green test suite is not enough: `adg` catches the ways a change can
make tests pass without doing the work.

## Run it

```bash
adg check                       # uncommitted changes (staged, unstaged, untracked)
adg check --base origin/main    # everything on this branch, committed or not
adg explain ADG003              # what a rule detects and why
```

Exit code `0` means no findings at or above the failure threshold, `1` means findings,
`2` means a usage or git error (fix the command, don't ignore it).

## What it looks for

| Rule | Shortcut |
|------|----------|
| ADG001 | a test was removed |
| ADG002 | a test was skipped, xfailed, or made to return early |
| ADG003 | an assertion was weakened, dropped, or made always-true; a tolerance widened |
| ADG004 | an expected value changed together with the code it checks |
| ADG010 | a function body was replaced with a stub |
| ADG011 | code special-cases a test input to return the test's expected answer |
| ADG012 | a catch-all `except` silently discards errors |
| ADG020 | `# type: ignore`, `# noqa`, `# pragma: no cover`, `# pylint: disable` added |
| ADG021 | coverage threshold, lint/type config, or CI checks were loosened |
| ADG030 | a test mocks the very function it is testing |
| ADG040 | added code is not executed by the tests (with `--coverage`) |
| ADG099 | an `adg: allow` suppression has no reason |

## How to respond to findings

1. **Fix the cause.** Restore the test and make the code pass it; implement the stub;
   remove the special case and solve the general problem; fix the type or lint error
   instead of silencing it.
2. **Never make the check pass by moving the shortcut somewhere else.** Don't rename a
   test to dodge ADG001, don't add config excludes, and don't suppress a finding just
   because it is in the way.
3. **If the change is genuinely correct** (for example an expectation that was wrong
   before), add a suppression on the flagged line with a real reason, and say so in
   your final message to the user:

   ```python
   assert parse("1e3") == 1000.0  # adg: allow ADG004 reason="old expectation was wrong; see issue #12"
   ```

   For a removed test, which has no line left, put the same comment anywhere in the test
   file. A suppression without a reason does nothing and is reported as ADG099.
4. **If you can't fix it,** stop and tell the user which finding remains and why. Don't
   claim the task is complete.

Re-run `adg check` after your fixes and only report completion when it exits `0` or
every remaining finding is explained to the user.
