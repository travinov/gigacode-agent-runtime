from __future__ import annotations

import re
from importlib.resources import files


def test_static_assets_are_packaged_and_have_no_external_dependencies() -> None:
    static = files("gigacode_agent_runtime.web").joinpath("static")
    names = {item.name for item in static.iterdir()}
    html = static.joinpath("index.html").read_text(encoding="utf-8")
    javascript = static.joinpath("app.js").read_text(encoding="utf-8")

    assert {"index.html", "app.js", "styles.css", "icons.svg"} <= names
    assert "http://" not in html
    assert "https://" not in html
    assert "<script>" not in html
    assert "history.replaceState" in javascript
    assert "window.location.hash" in javascript
    assert "EventSource" in javascript
    assert "Skills:" in javascript


def test_studio_assets_are_offline_and_cover_structured_editors() -> None:
    static = files("gigacode_agent_runtime.web").joinpath("studio_static")
    names = {item.name for item in static.iterdir()}
    html = static.joinpath("index.html").read_text(encoding="utf-8")
    javascript = static.joinpath("app.js").read_text(encoding="utf-8")
    help_javascript = static.joinpath("help.js").read_text(encoding="utf-8")

    assert {"index.html", "app.js", "help.js", "styles.css", "icons.svg"} <= names
    assert "http://" not in html
    assert "https://" not in html
    assert "http://" not in help_javascript
    assert "https://" not in help_javascript
    assert "<script>" not in html
    assert "history.replaceState" in javascript
    assert "window.location.hash" in javascript
    assert "/api/session" in javascript
    assert "/api/studio/catalog" in javascript
    assert "/api/studio/preview" in javascript
    assert "/api/studio/apply" in javascript
    assert "renderScenario" in javascript
    assert "renderNestedStep" in javascript
    assert "renderAgent" in javascript
    assert "renderSkill" in javascript
    assert "renderHelpTopic" in javascript
    assert "field-help-trigger" in javascript
    assert 'data-kind="help"' in html
    assert "/assets/help.js" in html
    assert "Создание сценариев" in help_javascript
    assert "Создание агентов" in help_javascript
    assert "Создание и назначение Skills" in help_javascript
    assert "best_effort" in help_javascript
    assert "1024\N{EN DASH}65535" in help_javascript
    assert help_javascript.count('topic: "') >= 50
    assert '["fail", "pause", "best_effort"]' in javascript
    assert "min: 1024" in javascript
    assert 'checkField("Открывать автоматически"' in javascript
    help_keys = set(
        re.findall(
            r'^    "([a-z]+(?:\.[a-z_]+)+)": \{$',
            help_javascript,
            re.MULTILINE,
        )
    )
    referenced_help_keys = set(
        re.findall(r'"((?:config|agent|skill|scenario)\.[a-z_.]+)"', javascript)
    )
    assert referenced_help_keys <= help_keys
    assert "textarea" in javascript
    assert "yaml" not in html.lower()
