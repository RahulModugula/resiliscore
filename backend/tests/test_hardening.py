"""Hardening: request ids, JSON access logs, env-driven CORS, /readyz and boundary validation."""

import json
import logging
import socket
import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.main import app, cors_origins
from app.observability import REQUEST_ID_HEADER, JsonFormatter, _incoming_request_id

SCORE = "/v1/parcel/score"
SCENARIO = {"scenario_id": "SCENARIO_1_LA_FLOOD"}
LOCAL_ORIGIN = "http://localhost:3000"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_incoming_request_id_is_honoured_echoed_and_set_on_body(client):
    resp = client.post(SCORE, json=SCENARIO, headers={REQUEST_ID_HEADER: "trace-abc.123"})
    assert resp.headers[REQUEST_ID_HEADER] == "trace-abc.123"
    assert resp.json()["request_id"] == "trace-abc.123"


def test_request_id_is_generated_when_absent(client):
    rid = client.get("/healthz").headers[REQUEST_ID_HEADER]
    assert uuid.UUID(rid)


def test_generated_request_id_is_fresh_per_request(client):
    assert (
        client.get("/healthz").headers[REQUEST_ID_HEADER] != client.get("/healthz").headers[REQUEST_ID_HEADER]
    )


@pytest.mark.parametrize("bad", ["x" * 129, "has space", "<script>", "a;b", "", "tab\tid"])
def test_unsafe_incoming_request_id_is_discarded(bad):
    scope = {"type": "http", "headers": [(b"x-request-id", bad.encode())]}
    assert _incoming_request_id(scope) is None


def test_unsafe_incoming_request_id_is_replaced_not_echoed(client):
    resp = client.get("/healthz", headers={REQUEST_ID_HEADER: "has space"})
    assert resp.headers[REQUEST_ID_HEADER] != "has space"
    assert uuid.UUID(resp.headers[REQUEST_ID_HEADER])


def test_headers_helper_is_case_insensitive():
    scope = {"type": "http", "headers": [(b"x-request-id", b"abc")]}
    assert Headers(scope=scope).get("X-Request-ID") == "abc"


def _access_lines(caplog) -> list[dict]:
    records = [r for r in caplog.records if r.name == "resiliscore.access"]
    return [json.loads(JsonFormatter().format(r)) for r in records]


def test_one_json_access_line_per_request(client, caplog):
    with caplog.at_level(logging.INFO, logger="resiliscore.access"):
        client.post(SCORE, json=SCENARIO, headers={REQUEST_ID_HEADER: "log-me-1"})
    lines = _access_lines(caplog)
    assert len(lines) == 1
    line = lines[0]
    assert line["message"] == "request"
    assert line["method"] == "POST"
    assert line["path"] == SCORE
    assert line["status"] == 200
    assert line["request_id"] == "log-me-1"
    assert isinstance(line["latency_ms"], float)
    assert line["latency_ms"] >= 0


def test_access_line_records_error_status(client, caplog):
    with caplog.at_level(logging.INFO, logger="resiliscore.access"):
        client.post(SCORE, json={"scenario_id": "SCENARIO_NOPE"})
    assert [line["status"] for line in _access_lines(caplog)] == [404]


def test_json_formatter_emits_one_object_per_line_without_access_fields():
    record = logging.LogRecord("resiliscore.test", logging.WARNING, __file__, 1, "plain %s", ("text",), None)
    line = json.loads(JsonFormatter().format(record))
    assert line["message"] == "plain text"
    assert line["level"] == "WARNING"
    assert "method" not in line and "request_id" not in line


def test_default_origin_is_allowed(client):
    resp = client.options(SCORE, headers={"Origin": LOCAL_ORIGIN, "Access-Control-Request-Method": "POST"})
    assert resp.headers["access-control-allow-origin"] == LOCAL_ORIGIN
    assert resp.headers[REQUEST_ID_HEADER]


def test_unlisted_origin_gets_no_cors_grant(client):
    resp = client.options(
        SCORE, headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in resp.headers


def test_cors_origins_default_when_unset_or_blank():
    assert cors_origins({}) == [LOCAL_ORIGIN]
    assert cors_origins({"RS_CORS_ORIGINS": "   "}) == [LOCAL_ORIGIN]


def test_cors_origins_parse_comma_separated_env():
    env = {"RS_CORS_ORIGINS": " https://a.example , https://b.example,"}
    assert cors_origins(env) == ["https://a.example", "https://b.example"]


def test_readyz_lists_upstreams_and_makes_no_network_calls(client, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("readyz must not open a connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    resp = client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert set(body["upstreams"]) == {"openfema", "usgs_3dep"}
    for upstream in body["upstreams"].values():
        assert upstream["configured"] is True
        assert upstream["url"].startswith("https://")


def test_healthz_unchanged(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_score_with_only_coordinates_is_422(client):
    assert client.post(SCORE, json={"lat": 45.0, "lng": -120.0}).status_code == 422


@pytest.mark.parametrize(("field", "value"), [("lat", 90.5), ("lat", -91), ("lng", 180.01), ("lng", -181)])
def test_out_of_range_coordinates_are_422(client, field, value):
    resp = client.post(SCORE, json={"address": "1 Nowhere Ln, Atlantis, XX", field: value})
    assert resp.status_code == 422


@pytest.mark.parametrize(("lat", "lng"), [(90, -180), (-90, 180)])
def test_boundary_coordinates_pass_validation(client, lat, lng):
    resp = client.post(SCORE, json={"address": "1 Nowhere Ln, Atlantis, XX", "lat": lat, "lng": lng})
    assert resp.status_code == 404
