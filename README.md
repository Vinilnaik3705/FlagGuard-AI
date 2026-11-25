# FlagGuard AI

Standalone feature release and incident investigation agent. Initial read-only telemetry analyzer; live Flagsmith, LLM, OpenTelemetry integration and dashboard are pending.

## Run

Python 3.12: create a virtual environment, install `pip install -r requirements.txt`, set `FLAGGUARD_API_KEY` to a random secret in your shell, then run `uvicorn flagguard.main:app`. API documentation: `/docs`. Run tests with `python -m pytest -q`.

See [architecture](docs/architecture.md). External test target: [OpenTelemetry Astronomy Shop](https://github.com/open-telemetry/opentelemetry-demo).
