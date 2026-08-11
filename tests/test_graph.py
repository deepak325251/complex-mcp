from benchmark.graph import evaluate, flatten_trace


def test_both_empty_is_perfect_refusal():
    r = evaluate([], [])
    assert r.f1 == 1.0
    assert r.exact_match is True
    assert r.tp == 0
    assert r.fp == 0
    assert r.fn == 0


def test_two_step_plan_correct_order():
    gt = [
        [{"server": "LightShop", "tool": "search_items"}],
        [{"server": "LightShop", "tool": "add_to_cart", "dependencies": [0]}],
    ]
    predicted = [
        ("LightShop", "search_items"),
        ("LightShop", "add_to_cart"),
    ]
    r = evaluate(gt, predicted)
    assert r.recall == 1.0
    assert r.tp == 2
    assert r.precision == 1.0
    assert r.f1 == 1.0
    assert r.exact_match is True


def test_two_step_plan_wrong_order_misplaces_dependent():
    gt = [
        [{"server": "LightShop", "tool": "search_items"}],
        [{"server": "LightShop", "tool": "add_to_cart", "dependencies": [0]}],
    ]
    predicted = [
        ("LightShop", "add_to_cart"),
        ("LightShop", "search_items"),
    ]
    r = evaluate(gt, predicted)
    # both nodes are covered so recall is still perfect
    assert r.recall == 1.0
    # the dependent node was placed before its prerequisite -> misplaced
    assert r.precision < 1.0
    assert r.tp == 1
    assert len(r.misplaced) == 1
    assert r.misplaced[0]["gt_node"] == 1


def test_flatten_trace_strips_prefix_and_skips_malformed():
    trace = [
        {"tool": "LightShop::search_items", "status": "ok"},
        {"tool": "LightShop::add_to_cart", "status": "rejected"},
        {"tool": "LightShop::broken", "status": "malformed"},
    ]
    out = flatten_trace(trace)
    assert out == [
        ("LightShop", "search_items"),
        ("LightShop", "add_to_cart"),
    ]
