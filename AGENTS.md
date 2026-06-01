# Codex Project Notes

- Always run Python commands through the repository virtual environment:
  - `./.venv/bin/python ...`
  - `./.venv/bin/python -m pytest ...`
- Do not use the system `python` / `python3` for syntax checks or tests in this repo. The project `.venv` is Python 3.12, and using another interpreter can produce false errors.
