"""OpenTelemetry tracing setup."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_tracing(
    service_name: str,
    otlp_endpoint: str,
    service_version: str = "0.1.0",
) -> None:
    """Initialise the OTel TracerProvider and wire it to the OTLP exporter.

    Call once at application startup (lifespan). Safe to call multiple times
    (subsequent calls are no-ops if provider is already set).
    """
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
        }
    )
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def get_tracer(name: str = "lex-agents-api") -> trace.Tracer:
    """Return a named tracer. Use in routers to create spans."""
    return trace.get_tracer(name)
