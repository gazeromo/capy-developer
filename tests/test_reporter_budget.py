import math

from capy_developer.desktop_cli import report_interval


def test_reporter_leaves_foreground_capacity_with_up_to_fifty_handoffs():
    # Exercise retained history as well as one active handoff against the
    # 300-proof-request window, including a sweep at the window boundary.
    for handoffs in range(1, 51):
        interval = report_interval(handoffs, 0)
        requests = (math.floor(600 / interval) + 1) * handoffs
        assert requests <= 200


def test_network_backoff_never_increases_reporter_request_pressure():
    for handoffs in (1, 5, 50):
        intervals = [report_interval(handoffs, failures) for failures in range(10)]
        assert intervals == sorted(intervals)
        assert min(intervals) >= 5
