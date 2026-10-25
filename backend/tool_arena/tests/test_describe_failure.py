"""describe_failure — naming the failure, not the task group that held it."""

from backend.tool_arena.comparison.describe_failure import describe_failure


def test_plain_exception_reads_as_type_and_message():
    assert describe_failure(ValueError("boom")) == "ValueError: boom"


def test_exception_group_names_the_sub_exception():
    """The symptom this exists for: an MCP call dying inside an anyio task
    group reported "unhandled errors in a TaskGroup (1 sub-exception)" and
    nothing else."""
    group = ExceptionGroup("unhandled errors in a TaskGroup", [RuntimeError("peer closed")])
    assert describe_failure(group) == "ExceptionGroup: RuntimeError: peer closed"


def test_every_sub_exception_is_named():
    group = ExceptionGroup("boom", [RuntimeError("a"), ValueError("b")])
    assert describe_failure(group) == "ExceptionGroup: RuntimeError: a; ValueError: b"


def test_nested_group_is_flattened():
    group = ExceptionGroup("outer", [ExceptionGroup("inner", [KeyError("k")])])
    assert "KeyError" in describe_failure(group)


def test_cause_is_followed():
    try:
        try:
            raise KeyError("missing")
        except KeyError as inner:
            raise RuntimeError("wrapper") from inner
    except RuntimeError as exc:
        described = describe_failure(exc)
    assert described.startswith("RuntimeError: wrapper <- KeyError")


def test_a_cycle_cannot_spin_forever():
    a = RuntimeError("a")
    b = RuntimeError("b")
    a.__cause__ = b
    b.__cause__ = a
    # Five links, then the depth cap prints the bare type and stops.
    assert describe_failure(a).count("RuntimeError") == 6
