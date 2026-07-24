from __future__ import annotations

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


def test_invalid_stream_json_is_rejected() -> None:
    parser = StreamJsonParser()
    parser.feed("{broken}\n")

    with pytest.raises(AgentRuntimeError) as captured:
        parser.finish()

    assert captured.value.code is ErrorCode.STEP_OUTPUT_INVALID


def test_json_result_envelope_is_normalized() -> None:
    assert parse_json_result('{"result":{"summary":"ok"}}') == {"summary": "ok"}
