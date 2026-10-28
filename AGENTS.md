# Project instructions

## Prompt protection — mandatory

Prompt content is user-owned and protected. Treat every prompt file, prompt template, embedded prompt string, sample prompt, system prompt, user prompt, and prompt-related configuration as read-only by default.

Protected prompt assets include, but are not limited to:

- files under any `prompts/` directory;
- files named `prompt.txt`, `*_prompt.txt`, `system_prompt.*`, or `user_prompt.*`;
- prompt text embedded in JSON, YAML, Python, tests, examples, or documentation;
- prompt text supplied by the user or copied from an attachment.

The following actions are forbidden without the user's explicit prior approval of the exact proposed change:

- rewriting, shortening, expanding, translating, reformatting, or “improving” prompt text;
- adding, removing, moving, or renaming prompt instructions, examples, fields, or placeholders;
- changing whitespace, punctuation, quotation marks, field order, output format, or examples when those are part of a prompt;
- creating, deleting, renaming, or moving a prompt asset;
- silently substituting a different prompt for tests, dry-runs, real API calls, or batch processing.

An instruction to refactor code, implement a task, fix a bug, make the framework generic, or add placeholder support does not authorize a prompt change.

### Required approval workflow

Before changing any protected prompt asset:

1. Show the user the exact proposed modification, preferably as a focused before/after diff.
2. Identify every prompt file or embedded prompt string that would change.
3. Explain why the prompt change is needed separately from code changes.
4. Wait for explicit user approval. Do not treat silence, broad implementation approval, or approval of unrelated code changes as permission.
5. Apply only the approved prompt edits. If another prompt change becomes necessary, stop and request approval again.

After an approved prompt change:

1. Show the actual resulting diff.
2. Show the complete final prompt content unless the user explicitly asks for a shorter report.
3. Verify that the saved prompt matches the approved text and report the verification result.
4. State whether any dry-run, test, or real API request used the changed prompt.

Runtime replacement of user-authored placeholders with row values is allowed only when it does not modify the saved prompt template. The framework must never automatically insert placeholders into or append input fields to a protected prompt.

If a task requires placeholders but the prompt does not contain them, fail validation and ask the user to approve the exact placeholder edits. Never infer their locations.
