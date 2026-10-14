# Open Source mini challenge: a contribution draft

The hackathon's Open Source mini challenge asks for a contribution to any open-source repository during the
hackathon window. Building FixTrail surfaced a small, real documentation bug that's a good first contribution.

**Nothing here has been submitted yet.** Opening the issue or pull request is your decision, from your own GitHub
account.

## The bug

The Agent Skills specification ([agentskills.io/specification](https://agentskills.io/specification), "Validation")
says to validate a skill with:

```bash
skills-ref validate ./my-skill
```

But `pip install skills-ref` (version 0.1.1) installs a command named **`agentskills`**, not `skills-ref`. The
documented command doesn't exist, while this works:

```bash
agentskills validate ./my-skill
```

(Friction log entry 8.)

## Where to report it

The repository linked from the spec: https://github.com/agentskills/agentskills (the `skills-ref` folder). Before
posting, check its open issues and pull requests in case someone already reported it, and read its contributing
guidelines.

## Draft issue

**Title:** Docs: `skills-ref validate` command doesn't exist after `pip install skills-ref` (installed command is `agentskills`)

**Body:**

> The specification's Validation section says to run `skills-ref validate ./my-skill`. After
> `pip install skills-ref` (0.1.1, Python 3.12, Windows 11), there is no `skills-ref` command; the package installs
> `agentskills` instead, and `agentskills validate ./my-skill` works as expected ("Valid skill").
>
> Suggested fix: either update the docs to `agentskills validate`, or add a `skills-ref` console script alias so both
> names work.
>
> Found while building an Agent Skill for the Amazon Developer Hackathon. Happy to open a PR for whichever option you
> prefer.

## If they welcome a pull request

The smallest change is a one-line docs edit in the specification's Validation section, from `skills-ref validate` to
`agentskills validate` (or the alias, if they choose that). Link the PR in the Devpost submission for the Open Source
mini challenge.
