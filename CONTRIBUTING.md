# Contributing

Thanks for your interest in PSX Decomp Studio. The project is at an early stage, so discussion is as valuable as code.

## Before you start

- Open an issue to discuss larger changes before writing code.
- **Never commit copyrighted game data.** That includes disc images, BIOS files, executables and extracted assets. Tests must use synthetic or freely licensed data. Common image formats are already in `.gitignore`.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Checks

Run these before opening a pull request. CI runs the same checks:

```bash
ruff check .
ruff format --check .
pytest
```

## Pull requests

- Keep each PR focused on one change.
- Add or update tests for behavior you change.
- By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
