from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.core.prompt_registry import PromptRegistry


@dataclass(frozen=True)
class Snippet:
    title: str
    body: str


def _parse_snippets(md: str) -> list[Snippet]:
    lines = md.splitlines()

    snippets: list[Snippet] = []
    current_title: str | None = None
    current_body_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_body_lines
        if current_title is None:
            return
        body = "\n".join(current_body_lines).strip("\n")
        snippets.append(Snippet(title=current_title.strip(), body=body))
        current_title = None
        current_body_lines = []

    for line in lines:
        if line.startswith("### "):
            flush()
            current_title = line.removeprefix("### ")
            current_body_lines = []
            continue

        if current_title is not None:
            current_body_lines.append(line)

    flush()
    return [s for s in snippets if s.body.strip()]


def _count_sentences(text: str) -> int:
    # Lightweight heuristic: count '.', '?', '!' as sentence boundaries.
    return sum(text.count(ch) for ch in (".", "?", "!"))


def _build_100_cases(snippets: list[Snippet]) -> list[tuple[str, str, str]]:
    # (title, body, rule_id)
    rules = [
        "no_red_heart",
        "no_em_dash",
        "has_bubble_separator_or_single",
        "no_other_fop",
        "no_prices_with_currency_symbols",
    ]

    if not snippets:
        return []

    cases: list[tuple[str, str, str]] = []

    # Generate deterministic 100 cases by cycling snippets and rules.
    i = 0
    while len(cases) < 100:
        snippet = snippets[i % len(snippets)]
        rule_id = rules[(i // len(snippets)) % len(rules)]
        cases.append((snippet.title, snippet.body, rule_id))
        i += 1

    return cases


@pytest.fixture(scope="module")
def snippets_content() -> str:
    registry = PromptRegistry()
    return registry.get("system.snippets").content


@pytest.fixture(scope="module")
def snippets(snippets_content: str) -> list[Snippet]:
    return _parse_snippets(snippets_content)


def test_snippets_file_has_sections(snippets: list[Snippet]) -> None:
    assert len(snippets) >= 5


@pytest.mark.parametrize(
    "title,body,rule_id",
    [],
)
def test_snippets_cases_placeholder(title: str, body: str, rule_id: str) -> None:
    # This test is replaced at import-time below.
    raise RuntimeError("Parametrization placeholder should not run")


def _assert_rule(title: str, body: str, rule_id: str) -> None:
    if rule_id == "no_red_heart":
        assert "❤️" not in body
        return

    if rule_id == "no_em_dash":
        assert "—" not in body
        return

    if rule_id == "has_bubble_separator_or_single":
        # Either the snippet uses '---' separators, or it's a single short bubble.
        has_sep = "\n---\n" in body or body.strip() == "---" or body.strip().startswith("---\n")
        is_single = "\n" not in body.strip() and len(body.strip()) > 0
        assert has_sep or is_single, f"Snippet '{title}' should be bubble-splittable via --- or be a single line"
        return

    if rule_id == "no_other_fop":
        # Snippets can mention Kutnyi explicitly; forbid other common variants.
        lowered = body.lower()
        assert "фоп" not in lowered or "кут" in lowered, f"Snippet '{title}' mentions FOP without Kutnyi"
        assert "ігорович" not in lowered or "не ігорович" in lowered
        return

    if rule_id == "no_prices_with_currency_symbols":
        # Prices should not be invented; forbid $/€ markers in canned templates.
        assert "$" not in body
        assert "€" not in body
        return

    raise ValueError(f"Unknown rule_id: {rule_id}")


def _install_parametrized_tests() -> None:
    # Mutate the placeholder test's parametrization dynamically so we can build
    # exactly 100 cases based on the current snippets content.
    registry = PromptRegistry()
    content = registry.get("system.snippets").content
    parsed = _parse_snippets(content)
    cases = _build_100_cases(parsed)

    param = pytest.mark.parametrize(
        "title,body,rule_id",
        cases,
        ids=[f"{title}::{rule_id}::{idx}" for idx, (title, _body, rule_id) in enumerate(cases)],
    )

    globals()["test_snippets_cases"] = param(
        lambda title, body, rule_id: _assert_rule(title=title, body=body, rule_id=rule_id)
    )


_install_parametrized_tests()


@pytest.mark.anyio
async def test_support_agent_injects_snippets() -> None:
    from src.agents.pydantic.support_agent import _add_manager_snippets

    injected = await _add_manager_snippets(None)  # type: ignore[arg-type]
    assert "ШАБЛОНИ МЕНЕДЖЕРА" in injected
    assert "# Шаблони менеджера" in injected
