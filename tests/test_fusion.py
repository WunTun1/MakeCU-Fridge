from fusion.reconcile import CameraObservation, NewRegion, VanishedItem, reconcile_shelf


def test_no_change_is_noop():
    decisions = reconcile_shelf(0, 1000, 1000, CameraObservation())
    assert decisions == []


def test_tiny_noise_is_ignored():
    decisions = reconcile_shelf(0, 1000, 1005, CameraObservation())
    assert decisions == []


def test_single_new_region_is_an_add():
    obs = CameraObservation(new_regions=[NewRegion(index=0, position=(0.5, 0.5))])
    decisions = reconcile_shelf(0, 1000, 1650, obs)
    assert len(decisions) == 1
    assert decisions[0].kind == "add"
    assert decisions[0].grams == 650


def test_weight_drop_with_no_vanished_item_is_consume():
    decisions = reconcile_shelf(0, 1000, 800, CameraObservation())
    assert len(decisions) == 1
    assert decisions[0].kind == "consume"
    assert decisions[0].grams == 200


def test_weight_drop_matching_vanished_item_is_remove():
    vanished = VanishedItem(item_id=1, product_id=10, grams=650)
    decisions = reconcile_shelf(0, 1650, 1000, CameraObservation(vanished=[vanished]))
    assert len(decisions) == 1
    assert decisions[0].kind == "remove"
    assert decisions[0].item_id == 1


def test_weight_drop_matches_best_subset_of_several_vanished_items():
    vanished = [
        VanishedItem(item_id=1, product_id=10, grams=650),
        VanishedItem(item_id=2, product_id=11, grams=500),
    ]
    # Only the 650g item actually left; the 500g one is just hidden behind something.
    decisions = reconcile_shelf(0, 1150, 500, CameraObservation(vanished=vanished))
    removes = [d for d in decisions if d.kind == "remove"]
    assert len(removes) == 1
    assert removes[0].item_id == 1


def test_weight_gain_alone_adds_nothing():
    assert reconcile_shelf(0, 1000, 1300, CameraObservation()) == []


def test_a_new_region_is_an_add_even_when_the_scale_did_not_move():
    obs = CameraObservation(new_regions=[NewRegion(index=0, position=(0.5, 0.5))])
    decisions = reconcile_shelf(0, 1000, 1003, obs)
    assert [d.kind for d in decisions] == ["add"] and decisions[0].grams == 0


def test_several_new_regions_are_each_added_sharing_the_weight():
    obs = CameraObservation(new_regions=[
        NewRegion(index=0, position=(0.3, 0.5)), NewRegion(index=1, position=(0.7, 0.5)),
    ])
    decisions = reconcile_shelf(0, 1000, 1950, obs)
    assert [d.kind for d in decisions] == ["add", "add"]
    assert [d.grams for d in decisions] == [475, 475]


def test_swap_removes_old_and_adds_new():
    vanished = VanishedItem(item_id=1, product_id=10, grams=650)
    obs = CameraObservation(vanished=[vanished], new_regions=[NewRegion(index=0, position=(0.5, 0.5))])
    # old item (650g) leaves, new item weighing 300g arrives -> net change is -350g
    decisions = reconcile_shelf(0, 1650, 1300, obs)
    kinds = {d.kind for d in decisions}
    assert "remove" in kinds
    assert "add" in kinds
    add = next(d for d in decisions if d.kind == "add")
    assert add.grams == 300
