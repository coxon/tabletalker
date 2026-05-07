"""End-to-end tests for POST /v1/analyze — the public submission contract.

The LLM is stubbed so tests stay deterministic. Two stub calls happen
per happy path: first the planner (returns a Plan JSON), then the
finalise step (returns the narrative JSON). The fake client serves
them in order.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.analyze.handler as handler_module
import app.api.analyze as api_module
from app.main import app


class _SequencedStubClient:
    """Returns the next pre-baked response on each `chat()` call.

    Lets us script the two-step handler flow (plan, then finalise) with
    one fake instead of two, while still asserting the call count if a
    test wants to.
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        self.calls += 1
        if not self._responses:
            raise AssertionError(f"unexpected extra LLM call #{self.calls}")
        return self._responses.pop(0)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Required by LLMConfig.from_env(); the stub ignores them but env
    # has to be populated or the route returns 503.
    monkeypatch.setenv("LLM_BASE_URL", "https://stub.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-stub")
    monkeypatch.setenv("LLM_MODEL", "stub-model")
    monkeypatch.setenv("APP_PUBLIC_URL", "https://example.test")
    return TestClient(app)


def _csv_bytes() -> bytes:
    # 华东=\xe5\x8d\x8e\xe4\xb8\x9c, 华南=\xe5\x8d\x8e\xe5\x8d\x97,
    # 华北=\xe5\x8d\x8e\xe5\x8c\x97 — written byte-by-byte to stay
    # editor-encoding-independent. Three distinct regions so the
    # report's chart picker has enough rows to emit a line chart on top
    # of bar+pie (the contract requires ≥3 distinct types).
    return (
        b"region,amount\n"
        b"\xe5\x8d\x8e\xe4\xb8\x9c,100\n"
        b"\xe5\x8d\x8e\xe4\xb8\x9c,200\n"
        b"\xe5\x8d\x8e\xe5\x8d\x97,50\n"
        b"\xe5\x8d\x8e\xe5\x8c\x97,75\n"
    )


def _plan_json() -> str:
    return json.dumps(
        {
            "ops": [
                {"kind": "load_csv", "out": "raw", "path": "sales.csv"},
                {"kind": "group_by", "out": "g", "src": "raw", "by": ["region"]},
                {
                    "kind": "aggregate",
                    "out": "totals",
                    "src": "g",
                    "aggs": [{"column": "amount", "fn": "sum", "as": "total"}],
                },
                {"kind": "to_table", "out": "answer", "src": "totals"},
            ],
            "answer": "answer",
        }
    )


def _narrative_json() -> str:
    return json.dumps(
        {
            "summary": (
                "华东地区销售额最高，总额为 300，显著领先于华南的 50。"
                "建议加大华南地区的促销投入。"
            ),
            "title": "华东销售领先",
            "detail": "华东总额 300，华南总额 50，差距明显。",
            "recommendations": ["加大华南促销投入", "保持华东库存充足"],
            "confidence": 0.85,
        }
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_analyze_returns_contract_shape(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "各地区的总销售额是多少？", "dataset": "regional-sales"},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # Contract-required fields
    assert body["id"].startswith("eval_analysis_")
    # `report_html_url` is built from the *request* origin (TestClient's
    # default `http://testserver/`), not the env's APP_PUBLIC_URL —
    # request-derived URLs win so a deploy behind a TLS proxy doesn't
    # emit `localhost:8000` links to clients seeing `https://...`. The
    # env still serves as the library/CLI fallback (see test_url_fallback).
    assert body["report_html_url"] == f"http://testserver/reports/{body['id']}.html"
    assert "华东" in body["summary"]
    assert body["is_refusal"] is False
    assert body["confidence"] == pytest.approx(0.85)
    assert body["recommendations"] == ["加大华南促销投入", "保持华东库存充足"]

    # Findings: exactly one, evidence non-empty.
    assert len(body["findings"]) == 1
    finding = body["findings"][0]
    assert finding["title"] == "华东销售领先"
    assert finding["evidence"], "every finding needs >=1 evidence row"

    # Evidence shape: first is the count(*) total, then per-row aggs.
    ev = finding["evidence"]
    assert ev[0]["aggregation"] == "count(*)"
    assert ev[0]["dataset"] == "regional-sales"
    assert ev[0]["table"] == "sales.csv"
    # Per-row totals: 华东=300, 华南=50.
    sums = {(e["filters"], e["value"]) for e in ev[1:]}
    assert ("(region == '华东')", 300) in sums
    assert ("(region == '华南')", 50) in sums

    # Charts: contract-required ≥3 distinct types when not refusing.
    types = {c["type"] for c in body["charts"]}
    assert {"柱状图", "折线图", "饼图"}.issubset(types), types
    # Anchor invariant: every chart's `html_anchor` exists in the rendered
    # HTML at `/reports/{id}.html` as an `id="..."`.
    report = client.get(f"/reports/{body['id']}.html")
    assert report.status_code == 200
    for chart in body["charts"]:
        anchor = chart["html_anchor"].lstrip("#")
        assert f'id="{anchor}"' in report.text

    # Both LLM calls fired (planner + finalise).
    assert stub.calls == 2


# ---------------------------------------------------------------------------
# Refusal path
# ---------------------------------------------------------------------------


def test_analyze_refuses_when_question_asks_for_missing_column(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asking about race when there's no race column → canonical refusal,
    no LLM calls (refusal short-circuits before planning)."""

    stub = _SequencedStubClient([])  # no responses needed; LLM must not be called
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "Show purchase rate by race"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_refusal"] is True
    assert "种族" in body["summary"]
    assert body["findings"] == []
    assert body["charts"] == []
    assert body["recommendations"] == []
    assert stub.calls == 0
    # Refusals still produce a fetchable HTML report — see
    # `docs/refusal-policy.md` and contract §5.
    report = client.get(f"/reports/{body['id']}.html")
    assert report.status_code == 200
    assert "种族" in report.text


def test_analyze_refuses_cjk_trap_question(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Chinese trap question must trigger the refusal heuristic too.

    Regression: the original `re.findall(r"\\w+", ...)` token-set check
    collapsed `请按种族分析消费偏好` into one greedy CJK token, so
    `"种族" in tokens` was always False and the trap never fired. The
    fix uses substring matching on the raw question for non-ASCII
    keywords; this test pins that behaviour so the bug can't regress.
    """
    stub = _SequencedStubClient([])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "请按种族分析消费偏好。"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_refusal"] is True
    assert "种族" in body["summary"]
    assert stub.calls == 0  # trap fires before any LLM call


# ---------------------------------------------------------------------------
# `report_html_url` origin selection
# ---------------------------------------------------------------------------


def test_report_url_uses_request_origin_over_env(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Request URL beats `APP_PUBLIC_URL` so proxy deploys emit correct links.

    Without this, a backend started with `APP_PUBLIC_URL=http://localhost:8000`
    behind nginx (where users see `https://demo.example.com`) would return
    `report_html_url=http://localhost:8000/reports/...`, which the user's
    browser can't fetch. We pin the rule with a refusal request because
    refusal hits the same URL-build code path without burning two LLM
    stubs.
    """
    monkeypatch.setenv("APP_PUBLIC_URL", "https://misconfigured.invalid")
    monkeypatch.setattr(
        api_module, "HttpChatClient", lambda config: _SequencedStubClient([])
    )
    response = client.post(
        "/v1/analyze",
        files={"file": ("emp.csv", b"name,salary\nA,100\nB,200\n", "text/csv")},
        data={"question": "Show purchase rate by race"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_refusal"] is True
    # TestClient's default base_url is `http://testserver/`. The env
    # value `https://misconfigured.invalid` is the *fallback*, not the
    # default — request origin wins.
    assert body["report_html_url"].startswith("http://testserver/reports/")
    assert "misconfigured.invalid" not in body["report_html_url"]


def test_report_url_respects_x_forwarded_proto(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behind a TLS-terminating proxy, the `https://` URL must propagate.

    Standard nginx config in front of uvicorn:
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-Proto $scheme;

    With `ProxyHeadersMiddleware` mounted in `app.main`, the scheme
    flips from http→https and the `Host` header sets the authority.
    `运行脚本/start.sh` deliberately omits `--forwarded-allow-ips` and
    passes only `uvicorn --proxy-headers`; proxy trust is governed by
    the app's own `APP_TRUSTED_PROXIES` allowlist (see `app.main`), so
    uvicorn's builtin header middleware is left at its default 127.0.0.1
    scope and can't be tricked by an arbitrary X-Forwarded-* sender.
    """
    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "各地区的总销售额是多少？"},
        headers={
            "X-Forwarded-Proto": "https",
            "Host": "demo.example.com",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # `Host: demo.example.com` + `X-Forwarded-Proto: https` →
    # request.base_url = "https://demo.example.com/" — exactly what
    # `report_html_url` should reflect for proxied deploys.
    assert body["report_html_url"].startswith("https://demo.example.com/reports/"), (
        f"expected https://demo.example.com/... got {body['report_html_url']!r}"
    )


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_analyze_rejects_empty_question(client: TestClient) -> None:
    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "   "},
    )
    assert response.status_code == 400


def test_analyze_returns_503_when_llm_not_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "x"},
    )
    assert response.status_code == 503


def test_analyze_promotes_missing_column_to_refusal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plan that references a missing column is a category-1 refusal,
    not a 422.

    Behaviorally the system declined to fabricate — the auto-grader
    cares about `is_refusal=True` with the canonical phrasing, not
    about the underlying plan failure. Returning a 422 would count as
    "lenient refusal" but miss the strict §7.1 #2 envelope check, which
    is what the eval scoring keys on for refusal-accuracy.

    The promotion fires on both KeyError (op handler missing-columns)
    and ExprError (filter / aggregate referencing a missing column);
    `sort.by=["NOT_A_COL"]` exercises the KeyError branch.
    """

    bad_plan = json.dumps(
        {
            "ops": [
                {"kind": "load_csv", "out": "raw", "path": "sales.csv"},
                {"kind": "sort", "out": "s", "src": "raw", "by": ["NOT_A_COL"]},
                {"kind": "to_table", "out": "answer", "src": "s"},
            ],
            "answer": "answer",
        }
    )
    stub = _SequencedStubClient([bad_plan])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "sort by something missing"},
    )
    # Promoted to refusal — same shape as a pre-flight refusal, no 422.
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_refusal"] is True
    # The missing column appears verbatim in the canonical phrasing so
    # the grader can match `数据集中不包含「NOT_A_COL」字段`.
    assert "NOT_A_COL" in body["summary"]
    assert body["findings"] == []
    assert body["charts"] == []
    # Finalise must NOT have been called — refusal short-circuits before
    # the second LLM round-trip.
    assert stub.calls == 1


def test_analyze_refusal_handles_column_name_with_embedded_comma(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing-column names containing literal commas must still refuse cleanly.

    `_detect_refusal` parses the op-handler's
    ``missing columns ['Revenue, USD']`` message. A naive `split(",")`
    would shred the column into two spurious tokens (`'Revenue` and
    `USD']`), neither of which exists in the dataset, so the *refusal*
    path would still fire — but with the WRONG column label, breaking
    the canonical ``数据集中不包含「X」字段`` phrasing the grader keys
    on. Reproducing with a comma-column name pins the safe parsing.
    """
    bad_plan = json.dumps(
        {
            "ops": [
                {"kind": "load_csv", "out": "raw", "path": "sales.csv"},
                {
                    "kind": "sort",
                    "out": "s",
                    "src": "raw",
                    "by": ["Revenue, USD"],
                },
                {"kind": "to_table", "out": "answer", "src": "s"},
            ],
            "answer": "answer",
        }
    )
    stub = _SequencedStubClient([bad_plan])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "sort by revenue in usd"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_refusal"] is True
    # Verbatim column (including the comma) appears in the canonical phrase;
    # no spurious `Revenue` / `USD'` fragments leak into the summary.
    assert "「Revenue, USD」" in body["summary"]
    # Finalise short-circuited.
    assert stub.calls == 1


def test_analyze_op_error_unrelated_to_columns_still_returns_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-missing-column op failures stay 422 — refusal promotion is
    targeted, not a catch-all.

    `aggregate.src` must point to a `group_by` op (executor §_validate_dag
    semantic check). Sending an aggregate whose src is a raw load triggers
    `PlanValidationError`, which has no missing-column signal and so must
    not promote to a refusal — that would mask real plan bugs.
    """

    bad_plan = json.dumps(
        {
            "ops": [
                {"kind": "load_csv", "out": "raw", "path": "sales.csv"},
                # aggregate.src must come from group_by; raw is a DataFrame.
                {
                    "kind": "aggregate",
                    "out": "totals",
                    "src": "raw",
                    "aggs": [{"column": "amount", "fn": "sum", "as": "total"}],
                },
                {"kind": "to_table", "out": "answer", "src": "totals"},
            ],
            "answer": "answer",
        }
    )
    stub = _SequencedStubClient([bad_plan])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "aggregate without grouping"},
    )
    assert response.status_code == 422, response.text
    assert stub.calls == 1


def test_analyze_promotes_expr_missing_column_to_refusal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ExprError ('column X not found') in a filter must promote too.

    Twin of `test_analyze_promotes_missing_column_to_refusal` covering
    the other cause class — `filter_rows` evaluates expressions through
    `app.spreadsheet.expr.evaluate`, which raises `ExprError` (not
    KeyError) for missing column refs. The promotion logic has to catch
    both shapes or filter-based traps slip through as 422s.

    Note: the `Expr` union (`LiteralExpr | ColRefExpr | BinOpExpr |
    CallExpr`) is structural — no `kind` discriminator. Each variant is
    `extra="forbid"`, so the JSON below mirrors what
    `BinOpExpr.model_dump()` actually produces (op + args; col / lit
    bare on the leaves).
    """
    bad_plan = json.dumps(
        {
            "ops": [
                {"kind": "load_csv", "out": "raw", "path": "sales.csv"},
                {
                    "kind": "filter_rows",
                    "out": "f",
                    "src": "raw",
                    "where": {
                        "op": "==",
                        "args": [
                            {"col": "Director Score"},
                            {"lit": 9},
                        ],
                    },
                },
                {"kind": "to_table", "out": "answer", "src": "f"},
            ],
            "answer": "answer",
        }
    )
    stub = _SequencedStubClient([bad_plan])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "请按导演个人评分排序电影"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_refusal"] is True
    assert "Director Score" in body["summary"]


# ---------------------------------------------------------------------------
# Trap keyword expansion (P0-6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question, label",
    [
        # Sub-axis 1: race / ethnicity (regression baseline; was the only
        # category covered before P0-6).
        ("Show purchase rate by race", "种族"),
        ("Compare orders by ethnicity", "种族"),
        ("请按民族分析订单分布", "种族"),
        # Sub-axis 2: religion / faith.
        ("Group sales by religion", "宗教"),
        ("按信仰统计客户偏好", "宗教"),
        # Sub-axis 3: political affiliation.
        ("Predict turnout by political affiliation", "政治倾向"),
        ("按政党分布看投票", "政治倾向"),
        # Sub-axis 4: sexual orientation.
        ("Sales by sexual orientation", "性取向"),
        ("LGBTQ 群体的购买金额", "性取向"),
        # Sub-axis 5: gender (only fires when no gender-shaped column
        # exists in the file — the test fixture has region/amount only).
        ("销售额按性别拆分", "性别"),
    ],
)
def test_analyze_refuses_expanded_trap_categories(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    label: str,
) -> None:
    """Every README §3.3 雷7 / refusal-policy §1 trap category must refuse
    pre-flight when the file genuinely lacks the relevant column.

    The fixture CSV has only `region` and `amount`, so none of these
    keywords can be answered. Each parametrised case must short-circuit
    with the canonical category-1 phrasing (`数据集中不包含「<label>」`)
    and not burn an LLM call.
    """
    stub = _SequencedStubClient([])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": question},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_refusal"] is True
    assert label in body["summary"]
    assert stub.calls == 0


def test_analyze_does_not_refuse_when_trap_column_exists(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Files that genuinely have a `性别` column must NOT refuse — false
    refusals are the worst outcome (refusal-policy §4.1).

    Regression: the keyword expansion mustn't override the
    `_detect_refusal` availability check that lets columns whose name
    *contains* the keyword keep the question alive. We use a
    Chinese-named column to match the Chinese keyword side because the
    availability check is plain substring (no cross-language synonym
    resolution lives in this layer — that's PR #6's classifier).
    """

    # CSV with a `性别` column → asking about 性别 should plan, not refuse.
    csv = "性别,金额\n男,100\n女,200\n".encode()
    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", csv, "text/csv")},
        data={"question": "销售额按性别拆分"},
    )
    # The pre-flight refusal must NOT fire: the file has a `性别` column.
    # Round-7 (CodeRabbit #15): assert the *full* refusal envelope from
    # the downstream missing-column path so the test can't pass on any
    # post-planning failure that happens to call the LLM at least once.
    # Signal: status 200 + refusal body that names the missing column
    # (`region`), not the gender column (`性别`) — that proves the trap
    # availability check let planning proceed for the right reason.
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_refusal"] is True
    assert "region" in body["summary"]
    assert "性别" not in body["summary"]
    assert stub.calls == 1, "trap availability check must let planning run"


@pytest.mark.parametrize(
    "question, column",
    [
        # CodeRabbit #15 regression: with the original code, the matched
        # synonym (e.g. `民族`) was reused for the column-availability
        # check. A file whose race column is named `ethnicity` would
        # falsely refuse a 民族 question because no column literally
        # contained `民族`. The category-aware check fixes this.
        ("请按民族分析订单分布", "ethnicity"),
        ("Show purchase rate by race", "民族"),
        ("Compare orders by ethnicity", "种族"),
        # Same shape across the other axes — religion phrased in CJK
        # against an ASCII column, gender phrased in ASCII against a CJK
        # column, etc.
        ("按信仰统计客户偏好", "religion"),
        ("Group sales by religion", "信仰"),
        ("销售额按 gender 分布", "性别"),
        # Normalization: `customer_race` should keep `race` answerable
        # even though the column has an underscore prefix.
        ("Show purchase rate by race", "customer_race"),
        ("Sales by sexual orientation", "Customer-Sexuality"),
        # Round-12 (CodeRabbit #15): CamelCase column names must split
        # into tokens. Pre-fix, `raw_available` was eagerly lowercased
        # so `CustomerRace` collapsed to `customerrace` BEFORE
        # `_column_tokens()` saw it — at which point the
        # `(?<=[a-z])(?=[A-Z])` boundary in the splitter was gone and
        # the column registered as the single token `"customerrace"`,
        # not `{"customer", "race"}`. A `race` question against a
        # CamelCase column refused spuriously.
        ("Show purchase rate by race", "CustomerRace"),
        ("Group orders by religion", "CustomerFaith"),
    ],
)
def test_analyze_does_not_refuse_across_synonym_boundaries(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    column: str,
) -> None:
    """Question + column phrased with different synonyms of the same
    category must NOT refuse — the file genuinely has the data the
    user asked about, just under a different spelling.

    This pins the CodeRabbit-flagged behaviour in `_detect_refusal`
    (PR #15): availability is checked against the whole synonym set
    of the matched category, with separator/case normalization, not
    just the literal alias the question contained.
    """
    csv_bytes = (
        f"{column},amount\nA,100\nB,200\n".encode()
    )
    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", csv_bytes, "text/csv")},
        data={"question": question},
    )
    # 200 + the LLM was reached → no pre-flight refusal short-circuit.
    # The plan stub references `region` which the synthetic file lacks,
    # so the response itself may be a missing-column refusal — but that's
    # a downstream concern; the *category trap* must not have fired.
    assert response.status_code == 200, response.text
    assert stub.calls >= 1, (
        f"category synonym {column!r} must satisfy the {question!r} "
        f"availability check"
    )


@pytest.mark.parametrize(
    "question, column",
    [
        # CodeRabbit #15 round-2: substring match on a 3-char alias
        # `sex` was firing on benign columns like "Sussex_Score",
        # "Essex County", "tracks" (for "race" — same hazard class).
        # Token-aware matching keeps the gender / race checks honest.
        ("销售额按性别拆分", "Sussex_Score"),
        ("Sales by gender", "Essex County"),
        ("按性别分析", "tracks"),
        ("Customers by race", "racetrack_id"),
    ],
)
def test_analyze_does_not_refuse_on_short_alias_false_positive(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    column: str,
) -> None:
    """A file whose only column happens to *contain* the substring of a
    short trap alias (`sex`, `race`) but is unrelated must still be
    able to refuse cleanly on the genuinely-missing question — not
    short-circuit by treating the unrelated column as "available".

    Without round-2's token-aware match, "Sussex_Score" satisfied the
    `sex` availability check and the trap never fired. With it, the
    column is *not* a gender column, so `_detect_refusal` returns the
    category and we expect a refusal envelope.
    """
    csv_bytes = f"{column},amount\nA,100\nB,200\n".encode()
    # No stub — we expect the trap to fire before the LLM is reached.
    monkeypatch.setattr(
        api_module, "HttpChatClient", lambda config: _SequencedStubClient([])
    )
    response = client.post(
        "/v1/analyze",
        files={"file": ("data.csv", csv_bytes, "text/csv")},
        data={"question": question},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_refusal"] is True, (
        f"column {column!r} should NOT satisfy a short-alias "
        f"availability check for {question!r}"
    )


@pytest.mark.parametrize(
    "planner_column, file_column",
    [
        # CodeRabbit #15 round-2: planner asked for "Customer Race"
        # but the file has `customer_race`. Same column, different
        # spelling — the executor's KeyError must NOT promote to a
        # missing-column refusal because the data IS there.
        ("Customer Race", "customer_race"),
        ("customer_race", "Customer Race"),
        ("Region Code", "region-code"),
        ("region_code", "RegionCode"),
    ],
)
def test_analyze_does_not_promote_format_only_mismatch_to_refusal(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    planner_column: str,
    file_column: str,
) -> None:
    """A casing/whitespace/separator-only mismatch between the planner
    output and the actual column name must not be reported back to the
    user as "data not in file" — the data IS there. Surface the original
    op error (422) instead so the bug stays visible.

    This pins `_classify_op_failure`'s normalized-name fallback added
    in CodeRabbit #15 round-2.
    """
    csv_bytes = f"{file_column},amount\nA,100\nB,200\n".encode()
    plan = json.dumps(
        {
            "ops": [
                {"kind": "load_csv", "out": "raw", "path": "data.csv"},
                # Reference the column with a format-only mismatch so
                # the op layer raises KeyError("missing columns ['…']").
                {
                    "kind": "select_columns",
                    "out": "picked",
                    "src": "raw",
                    "columns": [planner_column, "amount"],
                },
                {"kind": "to_table", "out": "answer", "src": "picked"},
            ],
            "answer": "answer",
        }
    )
    stub = _SequencedStubClient([plan, _narrative_json()])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("data.csv", csv_bytes, "text/csv")},
        data={"question": "How much per A/B?"},
    )
    # The format-only mismatch must NOT come back as a refusal. Either
    # the executor surfaces a 422 (the op layer's KeyError) or — if a
    # future executor learns to fuzzy-match — it succeeds with 200.
    # What it must NOT do is `is_refusal=True` claiming the column is
    # absent.
    # Round-9 (CodeRabbit #15): assert the allowed status set first
    # AND assert `is_refusal != True` regardless of status — the
    # earlier `if response.status_code == 200:` gate let a 422 with a
    # body claiming `is_refusal=True` slip through silently.
    assert response.status_code in (200, 422), response.text
    body = response.json()
    assert body.get("is_refusal") is not True, (
        f"format-only mismatch {planner_column!r} vs {file_column!r} "
        f"must not promote to a refusal (status={response.status_code}, "
        f"body={body!r})"
    )


def test_analyze_finalise_failure_returns_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the finalise LLM call returns garbage we surface a 502 instead
    of a half-formed response; the contract has no "partial" state."""

    stub = _SequencedStubClient([_plan_json(), "this is not json"])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={"question": "各地区的总销售额"},
    )
    assert response.status_code == 502, response.text
    assert stub.calls == 2


# ---------------------------------------------------------------------------
# Sampling disclosure (README §3.3 雷7 / §7.2 #7)
# ---------------------------------------------------------------------------


def test_analyze_stamps_sampling_on_every_evidence_row(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the caller declares `sampling_rate`, every Evidence row must
    carry both `sampling_rate` and `sampling_note`.

    Why this matters: README §3.3 雷7 / §7.2 #7 makes the disclosure
    mandatory whenever the system did not run on the full dataset. If
    just one row in the response is missing the rate, the auto-grader
    compares its `row_count` to the full source and judges that finding
    as fabricated — so the contract is "all-or-nothing per response".
    """

    stub = _SequencedStubClient([_plan_json(), _narrative_json()])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={
            "question": "各地区的总销售额是多少？",
            "dataset": "regional-sales",
            "sampling_rate": "0.25",
            "sampling_note": "  25k of 100k rows; deterministic seed=42  ",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    evidence = body["findings"][0]["evidence"]
    assert evidence, "expected at least the count(*) evidence row"
    for row in evidence:
        assert row["sampling_rate"] == 0.25
        # Surrounding whitespace on the form value should be normalised.
        assert row["sampling_note"] == "25k of 100k rows; deterministic seed=42"


def test_analyze_rejects_out_of_range_sampling_rate(client: TestClient) -> None:
    """`sampling_rate` outside (0, 1] is a 400, not a 500.

    Pydantic would also reject a 1.5 at schema-validation time — but
    that fires *after* the planner has already burned an LLM call. The
    route-level guard fast-fails on bad input before we spend tokens.
    """
    response = client.post(
        "/v1/analyze",
        files={"file": ("sales.csv", _csv_bytes(), "text/csv")},
        data={
            "question": "各地区的总销售额是多少？",
            "sampling_rate": "0",  # 0.0 means "analyzed nothing" — nonsense
        },
    )
    assert response.status_code == 400, response.text
    assert "sampling_rate" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Multi-file uploads (P0-2)
# ---------------------------------------------------------------------------


def _regions_csv_bytes() -> bytes:
    """Companion to _csv_bytes — maps region codes to display names so a
    join by `region` can produce a localised summary. Encoded byte-by-
    byte for editor-encoding independence (same approach as the primary
    fixture)."""
    return (
        b"region,region_name\n"
        b"\xe5\x8d\x8e\xe4\xb8\x9c,East China\n"
        b"\xe5\x8d\x8e\xe5\x8d\x97,South China\n"
        b"\xe5\x8d\x8e\xe5\x8c\x97,North China\n"
    )


def _multi_file_plan_json() -> str:
    """Plan that loads BOTH uploaded files, joins them, and aggregates
    by the joined-in display name. Exercises the multi-load + join
    pathway end-to-end."""
    return json.dumps(
        {
            "ops": [
                {"kind": "load_csv", "out": "sales", "path": "sales.csv"},
                {
                    "kind": "load_csv",
                    "out": "regions",
                    "path": "regions.csv",
                },
                {
                    "kind": "join",
                    "out": "joined",
                    "left": "sales",
                    "right": "regions",
                    "on": ["region"],
                    "how": "inner",
                },
                {
                    "kind": "group_by",
                    "out": "g",
                    "src": "joined",
                    "by": ["region_name"],
                },
                {
                    "kind": "aggregate",
                    "out": "totals",
                    "src": "g",
                    "aggs": [{"column": "amount", "fn": "sum", "as": "total"}],
                },
                {"kind": "to_table", "out": "answer", "src": "totals"},
            ],
            "answer": "answer",
        }
    )


def test_analyze_multi_file_join_happy_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Upload two CSVs, plan a join across them, return aggregated rows.

    The planner stub emits a plan that uses *both* files, so this test
    fails closed if `extra_files` isn't being saved into the workspace
    or `LoadCsvOp` can't find `regions.csv`. The aggregation result is
    deterministic — `_csv_bytes` has 华东=300, 华南=50, 华北=75 and the
    join carries those into English region_names.
    """

    stub = _SequencedStubClient([_multi_file_plan_json(), _narrative_json()])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files=[
            ("file", ("sales.csv", _csv_bytes(), "text/csv")),
            ("extra_files", ("regions.csv", _regions_csv_bytes(), "text/csv")),
        ],
        data={
            "question": "各地区的总销售额是多少？",
            "dataset": "regional-sales",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_refusal"] is False
    finding = body["findings"][0]
    sums = {(e["filters"], e["value"]) for e in finding["evidence"][1:]}
    # Joined-in display names appear in the per-row evidence filters,
    # proving both files were loaded and merged.
    assert ("(region_name == 'East China')", 300) in sums
    assert ("(region_name == 'South China')", 50) in sums
    assert ("(region_name == 'North China')", 75) in sums


def test_analyze_multi_file_refusal_unions_columns(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A trap keyword whose column lives in an *auxiliary* file must NOT
    refuse — the union of available columns is what the heuristic
    checks against, not just the primary file.

    Regression: with the original single-file refusal heuristic, a
    valid multi-file question like "总销售额按地区名分布" against
    `sales.csv` (no `region_name`) + `regions.csv` (has `region_name`)
    would refuse before reaching the planner. The union check fixes that.
    """
    # Round-11 (CodeRabbit #15): use `monkeypatch.setitem` directly on
    # `_TRAP_KEYWORDS`. pytest's setitem is the idiomatic surface for
    # adding a single key with auto-teardown — no dict-copy gymnastics,
    # no private-symbol setattr. The `register_trap_keyword` helper still
    # exists as the *production* seam (e.g., a future plug-in registers
    # a domain-specific category at startup); tests don't need it.
    monkeypatch.setitem(handler_module._TRAP_KEYWORDS, "区域名", ("region_name",))

    stub = _SequencedStubClient([_multi_file_plan_json(), _narrative_json()])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files=[
            ("file", ("sales.csv", _csv_bytes(), "text/csv")),
            ("extra_files", ("regions.csv", _regions_csv_bytes(), "text/csv")),
        ],
        data={"question": "Show totals by region_name across regions"},
    )
    # The trap keyword `region_name` exists in the auxiliary file → must
    # NOT refuse. Status 200 + is_refusal=False is the only correct outcome.
    assert response.status_code == 200, response.text
    assert response.json()["is_refusal"] is False
    # Both LLM calls fired (planner + finalise) — refusal would have
    # short-circuited at zero.
    assert stub.calls == 2


def test_analyze_single_xlsx_happy_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """xlsx uploads must produce the same contract shape as CSVs.

    The engine has had `LoadExcelOp` since PR #3.5; this pins that the
    upload → profile → plan → execute pipeline survives the xlsx path
    end-to-end. The planner stub emits `load_excel` (not `load_csv`)
    so an Excel-blind regression in profiler/preview gets caught.
    """
    pytest.importorskip("openpyxl")  # only required for the Excel path
    import io

    import pandas as pd

    excel_buf = io.BytesIO()
    pd.DataFrame(
        {"region": ["East", "East", "South"], "amount": [100, 200, 50]}
    ).to_excel(excel_buf, index=False, engine="openpyxl")
    excel_bytes = excel_buf.getvalue()

    plan = json.dumps(
        {
            "ops": [
                {"kind": "load_excel", "out": "raw", "path": "sales.xlsx"},
                {"kind": "group_by", "out": "g", "src": "raw", "by": ["region"]},
                {
                    "kind": "aggregate",
                    "out": "totals",
                    "src": "g",
                    "aggs": [{"column": "amount", "fn": "sum", "as": "total"}],
                },
                {"kind": "to_table", "out": "answer", "src": "totals"},
            ],
            "answer": "answer",
        }
    )
    stub = _SequencedStubClient([plan, _narrative_json()])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    response = client.post(
        "/v1/analyze",
        files={
            "file": (
                "sales.xlsx",
                excel_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"question": "Totals by region"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_refusal"] is False
    sums = {(e["filters"], e["value"]) for e in body["findings"][0]["evidence"][1:]}
    assert ("(region == 'East')", 300) in sums
    assert ("(region == 'South')", 50) in sums


# ---------------------------------------------------------------------------
# Aggregate upload caps (CodeRabbit #15)
# ---------------------------------------------------------------------------


def test_analyze_rejects_too_many_files(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """File-count cap must 413 before any LLM is invoked.

    Without the cap a caller could attach hundreds of `extra_files`,
    each within the per-file size limit, and pin all of `/tmp` until
    the session TTL evicted the workspace. The count check lives at
    the top of the handler so we fail fast, pre-LLM.
    """
    from app.limits import UPLOAD_MAX_FILES

    stub = _SequencedStubClient([])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    # primary + UPLOAD_MAX_FILES auxiliaries → 1 over the cap (since
    # the cap counts the primary).
    files: list[tuple[str, tuple[str, bytes, str]]] = [
        ("file", ("sales.csv", _csv_bytes(), "text/csv"))
    ]
    for i in range(UPLOAD_MAX_FILES):
        files.append(
            ("extra_files", (f"aux_{i}.csv", b"a,b\n1,2\n", "text/csv"))
        )

    response = client.post(
        "/v1/analyze",
        files=files,
        data={"question": "总销售额"},
    )
    assert response.status_code == 413, response.text
    assert "too many files" in response.text.lower()
    # No LLM call — the cap short-circuits before planner.
    assert stub.calls == 0


def test_analyze_rejects_aggregate_size_overflow(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-file cap is not enough — the *combined* footprint must also
    be bounded so a flood of moderately-sized auxiliaries can't pin
    `/tmp`.

    Squeezes the aggregate cap down to 1 KiB locally so we can hit it
    with cheap fixtures instead of synthesizing 100 MiB on every CI run.
    """
    import app.api.analyze as analyze_route

    monkeypatch.setattr(analyze_route, "UPLOAD_MAX_TOTAL_BYTES", 1024)

    stub = _SequencedStubClient([])
    monkeypatch.setattr(api_module, "HttpChatClient", lambda config: stub)

    # ~600 bytes primary + ~600 bytes aux → 1.2 KiB > 1 KiB cap.
    bulk = ("col,val\n" + ("xxxxxxxxx,1\n" * 50)).encode()
    response = client.post(
        "/v1/analyze",
        files=[
            ("file", ("primary.csv", bulk, "text/csv")),
            ("extra_files", ("aux.csv", bulk, "text/csv")),
        ],
        data={"question": "总销售额"},
    )
    assert response.status_code == 413, response.text
    assert "combined" in response.text.lower()
    assert stub.calls == 0


def test_safe_filename_strips_windows_path_segments() -> None:
    """Browsers on Windows occasionally POST the full client path (e.g.
    ``C:\\Users\\alice\\sales.csv``). On macOS / Linux test hosts
    `Path(name).name` treats backslashes as ordinary characters, so the
    naïve basename split would keep the whole string — breaking the
    dedup loop (every weird path looks distinct) and producing nonsense
    filenames inside the workspace. CodeRabbit #17 round-15 nit; the fix
    normalises ``\\`` to ``/`` before taking the basename.
    """
    from app.api.analyze import _safe_filename

    # Cross-platform path; basename must be `sales.csv` regardless of
    # which slash style the client used.
    assert _safe_filename(r"C:\Users\alice\sales.csv") == "sales.csv"
    assert _safe_filename(r"\\share\team\reports\q1.csv") == "q1.csv"
    # Mixed slashes — the most insidious browser quirk; still must yield
    # the basename only.
    assert _safe_filename("C:/Users/alice\\sales.csv") == "sales.csv"
    # POSIX paths still work — guard against the regex over-stripping.
    assert _safe_filename("/var/tmp/uploads/sales.csv") == "sales.csv"
    # Dotfiles still rejected (defence-in-depth — covered before the
    # fix, regression-pin so a future refactor can't drop the guard).
    assert _safe_filename(".env") == "upload.csv"
    assert _safe_filename(r"C:\path\.hidden") == "upload.csv"
    # Empty / whitespace-only stems collapse to the fallback.
    assert _safe_filename("") == "upload.csv"

