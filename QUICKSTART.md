# Quickstart

## 1. Install or Run In-Place

Preferred:

```bash
python3.14 -m pip install -e . --break-system-packages --no-build-isolation
```

Repo-local fallback:

```bash
python3 -m scripts.cli --help
```

## 2. Initialize Preferences

```bash
adaptive-cli onboard
```

If onboarding was already completed and you want a fresh run:

```bash
adaptive-cli onboard --reset
adaptive-cli onboard
```

## 3. Inspect What The Runtime Knows

```bash
adaptive-cli pref list
adaptive-cli digest weekly
adaptive-cli stats
```

## 4. Generate Host Context

```bash
adaptive-cli agent-context --compact --associated-limit 5 --context python code_review
```

## 5. Run Tests

```bash
python3 -m unittest discover -s tests -v
```

## 6. Read The Right Docs

- Overview: [README.md](./README.md)
- Current repo map: [docs/REPO_MAP.md](./docs/REPO_MAP.md)
- Claude adapter: [SKILL.md](./SKILL.md)
- Codex adapter: [plugins/adaptive-preferences](./plugins/adaptive-preferences)
- Historical iteration material: [docs](./docs)
