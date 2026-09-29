import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demos.context_compaction_demo import SYSTEM, build_demo_session, compact_demo
from finance_agent.context import estimate_tokens


def test_demo_visibly_compacts_without_mutating_canonical_history() -> None:
    session = build_demo_session()

    assert estimate_tokens([SYSTEM, *session.messages]) > 8_000
    compacted, report, unchanged = compact_demo(session, live=False)

    assert report.after_tokens < report.before_tokens
    assert {item["action"] for item in report.decisions} == {"keep", "trim", "drop"}
    assert unchanged is True
    assert compacted != [SYSTEM, *session.messages]
