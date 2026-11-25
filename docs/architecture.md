# Architecture

Core API accepts feature-attributed telemetry independent of application language. Initial single-workspace service uses SQLite and a bearer key. Do not expose it publicly as a multi-tenant service.

## OpenTelemetry Astronomy Shop
Upstream: https://github.com/open-telemetry/opentelemetry-demo (Apache-2.0). Use a separate checkout and retain upstream license and notices. Integration requires adding Flagsmith evaluation to a selected service and exporting actual evaluated flag attributes with request telemetry. Existing flagd switches must not be mistaken for Flagsmith state. The complete upstream demo is not assumed to fit 8 GB RAM; use a remote host or selected services after inspecting dependencies. OTLP adapter and live validation remain pending.

## Safety
The initial analyzer is read-only. Future LLM tools gather evidence only; a separate executor will require exact-plan approval, stale-state checks and post-write verification. No production credentials in source control.
