# office-delivery-gate

Validate and repair OOXML files (PPTX, DOCX, XLSX) before delivering them, and diagnose Office files that will not open.

## Install

```bash
git clone https://github.com/k5801kaohom-blip/office-delivery-gate.git
cd office-delivery-gate
./install.sh
```

`install.sh` installs into `${SKILLS_DIR:-$HOME/skills}` and runs a contract check on the
installed copy, so a clone that produced an unusable skill fails immediately instead of at
first use.

To install somewhere else:

```bash
SKILLS_DIR=/path/to/skills ./install.sh
```

If a skill with this name is already installed, the existing copy is moved aside to
`<name>.backup.<timestamp>` rather than overwritten.

## Package

```bash
./package.sh          # writes dist/office-delivery-gate-skill.zip
```

## Verify

```bash
./verify_skill_repo.sh                  # full check against origin/main
./verify_skill_repo.sh --offline        # local integrity only, no network
./verify_skill_repo.sh --skip-clone     # skip the fresh-clone stage
./verify_skill_repo.sh --api            # also check content served by GitHub
./verify_skill_repo.sh --json out.json  # machine-readable summary
```

The script checks seven things, and the last two are the ones that matter:

| Stage | Fails when |
| --- | --- |
| Commit sync | `HEAD` is not `origin/main`, or the working tree is dirty |
| Skill contract | SKILL.md names a resource that is not in the repository |
| Skill structure | frontmatter is invalid, or SKILL.md drifted past the length budget |
| Content equality | the remote does not carry the same bytes as the working tree |
| Payload hygiene | a repository file leaked into the skill directory |
| API surface | *(with `--api`)* GitHub serves different content than the working tree |
| Clone reproducibility | a fresh clone cannot install and pass its own contract check |

Exit code is `0` when everything passes and `1` when it does not, so the script is safe to
use as a CI gate. A skipped stage is not a passed stage — it is an unmeasured one, and the
summary reports skipped stages separately for that reason.

## Continuous integration

`.github/workflows/ci.yml` runs on every push, every pull request, a weekly schedule, and
manual dispatch. Four jobs:

| Job | What it proves |
| --- | --- |
| `repository integrity` | `verify_skill_repo.sh` passes on the pushed tree |
| `skill contract` | SKILL.md names files that exist, and the checker can actually fail |
| `skill payload check` | `install.sh` and `package.sh` work from a clean checkout |
| `summary` | aggregates every report into the run summary, and fails the run if any job failed |

### The failure CI exists to catch

**SKILL.md documenting a file that was never committed.**

The skill looks complete. The contract check passes on the author's machine, because the file
is still there. Everyone who clones gets a skill that documents a pipeline it does not
contain. Only a clean clone detects it.

### The second failure: a checker that never fails

A contract checker that always returns success is worse than no checker, because it
manufactures confidence while detecting nothing. A green contract stage is only evidence if
the checker has been shown to reject a broken skill.

`ci_negative_control.py` runs the checker against copies of the skill that are deliberately
broken — a documented file removed, a script made non-executable, a script given a syntax
error — and fails the build if any fault slips through. It also re-checks the real skill
afterwards, so a fault that leaks into the working tree cannot pass unnoticed.

Run it locally before trusting a green contract stage:

```bash
python3 office-delivery-gate/scripts/ci_negative_control.py --skill office-delivery-gate
```

## Releases

`.github/workflows/release.yml` publishes a tagged commit as a downloadable archive:

```bash
git tag -a v1.0.0 -m "v1.0.0"
git push origin v1.0.0
```

The workflow re-verifies the **tagged tree** rather than trusting that CI passed on that
commit. A tag can be placed on a commit that never ran CI, or on one whose checks passed days
earlier. The archive is attached only after verification succeeds on the tagged tree, and the
release notes carry the verification report so the claim is inspectable.

## Layout

```
office-delivery-gate/
├── office-delivery-gate/          # the skill payload; this is what gets installed
│   ├── SKILL.md
│   ├── scripts/
│   ├── references/
│   └── templates/
├── .github/workflows/
│   ├── ci.yml
│   └── release.yml
├── scripts/                 # repository tooling, not skill payload
│   ├── check_skill_contract.py
│   ├── ci_negative_control.py
│   └── ci_summary.py
├── install.sh
├── package.sh
├── verify_skill_repo.sh
├── LICENSE
└── README.md
```

The skill sits in a subdirectory on purpose. Everything that is not skill payload — above all
`.gitignore` — stays at the repository root, so it never lands in `~/skills/<name>/`. Git
reads a `.gitignore` from an ancestor directory, so a leaked one can silently change which
files a user's own repository tracks. `verify_skill_repo.sh` fails the build when it happens.

## Requirements

Python 3.10 or newer; standard library only.

## License

MIT — see [LICENSE](LICENSE).