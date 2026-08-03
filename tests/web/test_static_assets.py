from __future__ import annotations

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

    assert {"index.html", "app.js", "styles.css", "icons.svg"} <= names
    assert "http://" not in html
    assert "https://" not in html
    assert "<script>" not in html
    assert "history.replaceState" in javascript
    assert "window.location.hash" in javascript
    assert "/api/studio/catalog" in javascript
    assert "/api/studio/preview" in javascript
    assert "/api/studio/apply" in javascript
    assert "renderScenario" in javascript
    assert "renderNestedStep" in javascript
    assert "renderAgent" in javascript
    assert "renderSkill" in javascript
    assert "textarea" in javascript
    assert "yaml" not in html.lower()
