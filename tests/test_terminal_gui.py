from io import BytesIO

from terminal_gui import iter_sse


def test_iter_sse_parses_multiple_and_multiline_events():
    stream = BytesIO(
        b'event: navigator\n'
        b'data: {"sub_questions": []}\n\n'
        b'event: stats\n'
        b'data: {"total_tokens":\n'
        b'data: 42}\n\n'
    )

    assert list(iter_sse(stream)) == [
        ("navigator", {"sub_questions": []}),
        ("stats", {"total_tokens": 42}),
    ]
