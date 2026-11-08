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

