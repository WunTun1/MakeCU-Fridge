import numpy as np

import main


def _frame(v):
    return np.full((4, 4, 3), v, np.uint8)


def test_door_close_uses_the_view_from_before_the_door_began_closing():
    reference = _frame(120)
    history = [(0.0, _frame(130)), (0.5, _frame(131)), (9.5, _frame(60)), (9.9, _frame(20))]  # last two: closing
    view = main._open_view(history, reference, now=10.0)
    assert view is not None and view.mean() >= 125


def test_a_half_dark_picture_is_never_used():
    reference = _frame(120)
    history = [(0.0, _frame(50)), (1.0, _frame(40))]  # all far darker than the scene
    assert main._open_view(history, reference, now=10.0) is None


def test_no_view_yet_means_no_comparison():
    assert main._open_view([(9.9, _frame(120))], _frame(120), now=10.0) is None


class _Scale:
    num_shelves = 1

    def __init__(self, grams):
        self.grams = grams

    def weigh_all(self):
        return {0: self.grams}


def test_a_trip_that_moved_nothing_keeps_the_before_photo(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_handle_trip", lambda *a: calls.append(a))
    before, held = _frame(100), _frame(140)  # the food's in view but still in the hand
    ref, weights = main._measure_trip(None, None, _Scale(502), before, {0: 500.0}, after_frame=held)
    assert ref is before and weights == {0: 500.0} and calls == []
    ref, weights = main._measure_trip(None, None, _Scale(803), ref, weights, after_frame=held)
    assert calls and calls[0][3] is before  # the real trip compares against the photo without it
    assert ref is held and weights == {0: 803}


def test_a_tiny_patch_is_swapped_for_the_whole_shelf():
    assert main._band_box((0.0, 0.5), (480, 640, 3)) == (0, 0, 640, 240)
