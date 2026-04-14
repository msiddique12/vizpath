"""Utilities to extract critical OpenAPI contract snapshots."""

from __future__ import annotations

from typing import Any

CRITICAL_PATH_METHODS: dict[str, tuple[str, ...]] = {
    "/api/v1/intelligence/analyze": ("post",),
    "/api/v1/intelligence/failure-modes": ("post",),
    "/api/v1/intelligence/copilot": ("post",),
    "/api/v1/intelligence/status": ("get",),
    "/api/v1/projects/me/budget/status": ("get",),
}

CRITICAL_COMPONENT_SCHEMAS: tuple[str, ...] = (
    "AnalyzeRequest",
    "FailureModesRequest",
    "TraceCopilotRequest",
    "ProjectBudgetStatusResponse",
)


def _extract_operation_contract(operation: dict[str, Any]) -> dict[str, Any]:
    request_body = operation.get("requestBody") or {}
    request_schema = (
        request_body.get("content", {})
        .get("application/json", {})
        .get("schema")
    )

    responses: dict[str, Any] = {}
    for status_code in sorted(operation.get("responses", {}).keys()):
        response = operation["responses"][status_code]
        response_schema = (
            response.get("content", {})
            .get("application/json", {})
            .get("schema")
        )
        responses[status_code] = {
            "description": response.get("description"),
            "json_schema": response_schema,
        }

    return {
        "operation_id": operation.get("operationId"),
        "request_body_required": bool(request_body.get("required", False)),
        "request_json_schema": request_schema,
        "responses": responses,
    }


def extract_critical_openapi_contract(openapi_doc: dict[str, Any]) -> dict[str, Any]:
    """Extract a stable, critical subset of OpenAPI for contract locking."""
    paths = openapi_doc.get("paths", {})
    components = openapi_doc.get("components", {}).get("schemas", {})

    critical_paths: dict[str, Any] = {}
    for path, methods in CRITICAL_PATH_METHODS.items():
        path_item = paths.get(path, {})
        method_contracts: dict[str, Any] = {}
        for method in methods:
            operation = path_item.get(method)
            if operation is None:
                method_contracts[method] = None
                continue
            method_contracts[method] = _extract_operation_contract(operation)
        critical_paths[path] = method_contracts

    critical_components: dict[str, Any] = {}
    for schema_name in CRITICAL_COMPONENT_SCHEMAS:
        critical_components[schema_name] = components.get(schema_name)

    return {
        "schema_version": 1,
        "critical_paths": critical_paths,
        "critical_components": critical_components,
    }
