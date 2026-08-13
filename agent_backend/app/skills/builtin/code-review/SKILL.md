---
name: code-review
description: Review code for bugs, behavioral regressions, and missing tests.
when: User asks for a code review or to audit a change.
version: 1.0.0
scope: builtin
---

## Steps
1. Read the changed files and the surrounding modules.
2. Look for correctness bugs, regressions, and missing test coverage.
3. Order findings by severity and reference exact file and line numbers.
4. Keep summaries brief and place them after the findings.

## Constraints
- Do not rewrite the code during a review unless explicitly asked.
- Separate audit findings from optional suggestions.
