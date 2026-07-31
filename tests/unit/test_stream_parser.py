from __future__ import annotations

import json

import pytest

from gigacode_agent_runtime.adapters.stream_parser import StreamJsonParser, parse_json_result
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode


def test_stream_parser_handles_arbitrary_chunk_boundaries() -> None:
    parser = StreamJsonParser()

    parser.feed('{"type":"message","content":"hel')
    parser.feed('lo"}\n{"type":"result","result":{"approved":true}}\n')
    parsed = parser.finish()

    assert parsed.result == {"approved": True}
    assert len(parsed.events) == 2


@pytest.mark.parametrize(
    "encoded",
    [
        '{"approved":true}',
        '\n\n```json\n{"approved":true}\n```',
    ],
)
def test_stream_parser_normalizes_corporate_string_result(encoded: str) -> None:
    parser = StreamJsonParser()
    parser.feed(
        f'{{"type":"result","subtype":"success","is_error":false,"result":{json.dumps(encoded)}}}\n'
    )

    assert parser.finish().result == {"approved": True}


def test_invalid_stream_json_is_rejected() -> None:
    parser = StreamJsonParser()
    parser.feed("{broken}\n")

    with pytest.raises(AgentRuntimeError) as captured:
        parser.finish()

    assert captured.value.code is ErrorCode.STEP_OUTPUT_INVALID


def test_json_result_envelope_is_normalized() -> None:
    assert parse_json_result('{"result":{"summary":"ok"}}') == {"summary": "ok"}


def test_json_result_accepts_fenced_string() -> None:
    encoded = json.dumps('```json\n{"summary":"ok"}\n```')

    assert parse_json_result(f'{{"result":{encoded}}}') == {"summary": "ok"}


@pytest.mark.parametrize(
    "value",
    [
        'prefix {"approved":true}',
        '```json\n{"approved":true}\n``` suffix',
        '```json\n{"approved":true}\n```\n```',
    ],
)
def test_stream_parser_rejects_ambiguous_string_result(value: str) -> None:
    parser = StreamJsonParser()
    parser.feed(f'{{"type":"result","result":{json.dumps(value)}}}\n')

    with pytest.raises(AgentRuntimeError) as captured:
        parser.finish()

    assert captured.value.code is ErrorCode.STEP_OUTPUT_INVALID
