from value_investor import moat


def summary(**kw):
    base = {"history_years": 10, "loss_years": 0, "roe_good_share": 0.9, "eps_up_share": 0.8, "net_margin": 0.2}
    return {**base, **kw}


def test_a_brand_shows_as_a_high_gross_margin_that_barely_moves():
    s = summary(gross_margin=0.61, gross_margin_std=0.01, sga_to_gp=0.52, capex_to_ni=0.21, debt_years=3.7)
    m = moat.classify(s)
    assert m["kind"] == "unique product" and m["short"] == "Product"
    labels = [label for label, _, _ in m["evidence"]]
    assert labels[:3] == ["Gross margin", "SG&A of gross profit", "Capex of net income"]


def test_a_toll_bridge_files_no_cost_of_sales():
    s = summary(operating_margin=0.54, operating_margin_std=0.03, capex_to_ni=0.04, net_margin=0.45)
    assert moat.classify(s)["kind"] == "unique service"


def test_a_low_cost_operator_turns_a_thin_steady_margin_into_high_returns():
    s = summary(gross_margin=0.13, gross_margin_std=0.01, gp_to_assets=0.43, roe_good_share=1.0, eps_up_share=1.0,
                net_margin=0.03)
    assert moat.classify(s)["kind"] == "low-cost operator"


def test_swings_and_losses_read_as_no_advantage():
    s = summary(gross_margin=0.19, gross_margin_std=0.06, loss_years=2, roe_good_share=0.2, capex_to_ni=2.5)
    m = moat.classify(s)
    assert m["kind"] == "none"
    assert ("EPS up on the year", "in 80% of years, 2 with a loss", "fail") in m["evidence"]


def test_banks_and_short_histories_are_not_classified():
    assert moat.classify(summary(gross_margin=0.6, gross_margin_std=0.01), industry="Banks - Regional")["kind"] is None
    assert moat.classify(summary(gross_margin=0.6, gross_margin_std=0.01), profile="financial")["kind"] is None
    assert moat.classify(summary(history_years=3))["kind"] is None
