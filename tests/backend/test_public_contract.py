from __future__ import annotations

from app.main import admin_app, public_app


def test_public_openapi_exposes_only_safe_typed_contracts() -> None:
    spec = public_app.openapi()
    paths = spec["paths"]
    assert "/competitions/{competition_id}/stream" in paths
    assert "/competitions/{competition_id}/chart" in paths
    assert "/decisions/{decision_id}/artifact" in paths
    assert "/stream" not in paths
    decision = spec["components"]["schemas"]["DecisionDTO"]["properties"]
    assert "justification" in decision
    status_code = decision["provider_status_code"]["anyOf"]
    integer_schema = next(item for item in status_code if item.get("type") == "integer")
    assert integer_schema["minimum"] == 100
    assert integer_schema["maximum"] == 599
    assert {item.get("type") for item in status_code} == {"integer", "null"}
    assert "reasoning" not in decision
    assert "private_reasoning" not in decision
    public_schema_text = str(spec).lower()
    assert "api_key_env" not in public_schema_text
    assert "password_hash" not in public_schema_text
    assert "provider_api_key" not in public_schema_text


def test_history_routes_use_bounded_page_envelopes() -> None:
    spec = public_app.openapi()
    for route in (
        "/competitions/{competition_id}/equity",
        "/competitions/{competition_id}/decisions",
        "/competitions/{competition_id}/positions",
        "/competitions/{competition_id}/trades",
    ):
        schema = spec["paths"][route]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert schema["$ref"].startswith("#/components/schemas/PageDTO_")
    page = spec["components"]["schemas"]["PageDTO_EquityPoint_"]["properties"]
    assert set(page) == {"items", "limit", "offset", "total"}
    chart = spec["paths"]["/competitions/{competition_id}/chart"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert chart["$ref"] == "#/components/schemas/EquityChartDTO"
    events = spec["components"]["schemas"]["EventPageDTO"]["properties"]
    assert set(events) == {"items", "after", "next_after", "has_more"}


def test_admin_contract_has_no_unauthenticated_openapi_route() -> None:
    spec = admin_app.openapi()
    assert "/openapi.json" not in spec["paths"]
    assert "/competitions/{competition_id}/{action}" in spec["paths"]
