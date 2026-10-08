# `mflux-pr-docs` AI Agent Skill


***An AI skill that helps you write the PR body. It works in Claude Code, Cursor and GitHub Copilot.***


### Goals
 1. The AI writes short, clear text in Simplified Technical English \*.
 2. The AI fills the `What` section. See `pr-what-prompt.md`.
 3. The AI fills the `release-note` block. See `release-note-prompt.md`.


### Process:
1. Read `git diff main...HEAD`, the commit log and the linked issues.
1. Copy `.github/pull_request_template.md` to `tmp-PR-content.md`.
1. Fill in the `What` section (the benefit prompt), the `release-note` block, and the `Verification` section from commands that were actually run.
1. Run the same regex check as CI on `tmp-PR-content.md`.
1. Show `tmp-PR-content.md` to the developer for approval or edits. Only after approval does it run `gh pr create --body-file tmp-PR-content.md`, or `gh pr edit` if the PR already exists.


\* Simplified Technical English skill - [asd-ste100-skill](https://github.com/danyuchn/asd-ste100-skill)
