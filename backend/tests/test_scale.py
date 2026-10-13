import pytest

from app.scale import (MM_PER_PT, ScaleError, calibrate_two_point, detect_page_size, parse_stated_scales,
                       pick_title_block_scale, polyline_length, stated_m_per_pt, verify)


def pt(mm):
    return mm / MM_PER_PT


def test_page_size_detection():
    assert detect_page_size(pt(841), pt(594)) == "A1"
    assert detect_page_size(pt(594), pt(841)) == "A1"  # portrait
    assert detect_page_size(pt(420), pt(297)) == "A3"
    assert detect_page_size(pt(1189), pt(841)) == "A0"
    assert detect_page_size(pt(500), pt(500)) == "custom"


def test_parse_scales():
    s = parse_stated_scales("SCALE 1:100 @ A1  DETAIL 1 : 20")
    assert [(x.ratio, x.paper) for x in s] == [(100, "A1"), (20, None)]
    assert parse_stated_scales("1:200 at a3")[0].paper == "A3"
    assert parse_stated_scales("no scale here") == []


def test_title_block_scale_prefers_paper_size():
    assert pick_title_block_scale("1:20 1:20 1:100 @ A1").ratio == 100
    assert pick_title_block_scale("1:50 1:20 1:50").ratio == 50


def test_stated_scale_at_intended_size():
    # 1:100 on an A1 page: 1 mm on paper = 100 mm = 0.1 m
    mpp = stated_m_per_pt(100, "A1", pt(841), pt(594))
    assert mpp * pt(1) == pytest.approx(0.1)


def test_a1_drawing_saved_at_a3_is_corrected():
    # Saved at A3, every mm on the page stands for 841/420 mm at A1.
    mpp = stated_m_per_pt(100, "A1", pt(420), pt(297))
    assert mpp * pt(1) == pytest.approx(0.1 * 841 / 420)


def test_two_point_calibration():
    mpp = calibrate_two_point((0, 0), (pt(100), 0), 10.0)
    assert polyline_length([(0, 0), (pt(50), 0), (pt(50), pt(30))]) * mpp == pytest.approx(8.0)


def test_calibration_rejects_bad_input():
    with pytest.raises(ScaleError):
        calibrate_two_point((0, 0), (0, 0.5), 10)
    with pytest.raises(ScaleError):
        calibrate_two_point((0, 0), (100, 0), 0)


def test_verify_within_and_outside_tolerance():
    mpp = calibrate_two_point((0, 0), (pt(100), 0), 10.0)
    assert verify(mpp, (0, 0), (0, pt(50)), 5.0).ok
    assert verify(mpp, (0, 0), (0, pt(50)), 5.05).ok  # exactly 1% (0.99% of 5.05)
    bad = verify(mpp, (0, 0), (0, pt(50)), 5.2)
    assert not bad.ok and bad.error_pct == pytest.approx(3.846, abs=0.01)
