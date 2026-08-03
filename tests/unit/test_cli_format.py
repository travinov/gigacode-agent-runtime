from __future__ import annotations

from gigacode_agent_runtime.cli_format import terminal_hyperlink


def test_terminal_hyperlink_uses_osc8_and_plain_url_fallback() -> None:
    url = "http://127.0.0.1:43210/#token=test"

    rendered = terminal_hyperlink("Открыть Runtime Studio", url, enabled=True)

    assert rendered.startswith(f"\033]8;;{url}\033\\")
    assert "Открыть Runtime Studio" in rendered
    assert rendered.endswith(f"\n{url}")


def test_terminal_hyperlink_is_plain_when_osc8_is_unavailable() -> None:
    url = "http://127.0.0.1:43210/#token=test"

    assert terminal_hyperlink("Studio", url, enabled=False) == url
