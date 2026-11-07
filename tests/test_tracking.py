import cv2
import numpy as np

from vision.change import detect_changes
from vision.tracking import KnownItem, color_histogram, match, normalized_position, patch_box

W, H = 640, 240
BG = (42, 40, 38)
RED, BLUE, GREEN = (40, 40, 220), (220, 80, 40), (60, 180, 75)


def frame(*boxes):
    img = np.full((H, W, 3), BG, np.uint8)
    for (x, y, w, h), color in boxes:
        cv2.rectangle(img, (x, y), (x + w, y + h), color, -1)
    return img


def known(item_id, box, before):
    pos = normalized_position(box, before.shape)
    return KnownItem(item_id, pos, color_histogram(before, patch_box(pos, before.shape)))


MILK = (60, 80, 80, 120)
EGGS = (300, 120, 80, 80)


def test_untouched_item_is_not_vanished_when_something_else_is_added():
    before = frame((MILK, RED))
    after = frame((MILK, RED), (EGGS, BLUE))
    result = match([known(1, MILK, before)], detect_changes(before, after), before, after)
    assert result.vanished_item_ids == []
    assert len(result.new_regions) == 1
    assert result.moved == []


def test_removed_item_is_vanished():
    before = frame((MILK, RED), (EGGS, BLUE))
    after = frame((EGGS, BLUE))
    items = [known(1, MILK, before), known(2, EGGS, before)]
    result = match(items, detect_changes(before, after), before, after)
    assert result.vanished_item_ids == [1]
    assert result.new_regions == []


def test_moved_item_is_a_move_not_remove_plus_add():
    before = frame((MILK, RED))
    after = frame(((450, 80, 80, 120), RED))
    result = match([known(1, MILK, before)], detect_changes(before, after), before, after)
    assert [item_id for item_id, _ in result.moved] == [1]
    assert result.vanished_item_ids == []
    assert result.new_regions == []


def test_swap_for_different_looking_item_is_remove_plus_new():
    before = frame((MILK, RED))
    after = frame(((450, 80, 80, 120), GREEN))
    result = match([known(1, MILK, before)], detect_changes(before, after), before, after)
    assert result.vanished_item_ids == [1]
    assert len(result.new_regions) == 1
