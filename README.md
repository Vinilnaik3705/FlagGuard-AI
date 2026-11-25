# FlagGuard AI

A reusable, human-approved feature release and incident investigation agent for Flagsmith. OpenTelemetry Astronomy Shop is an external integration target, not a dependency of the core.

## Status
Initial implementation; live provider and Astronomy Shop validation pending.

## Design
Applications send feature-attributed telemetry via a versioned HTTP API. The agent compares cohorts, gathers evidence, proposes actions, and never writes flags directly. A separate executor validates approvals and restores verified snapshots.

## Upstream
[OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo) (Apache-2.0). Upstream code is not modified by this repository.

## Local development
Python 3.12 recommended. Use a virtual environment. See docs/architecture.md for integration requirements.
