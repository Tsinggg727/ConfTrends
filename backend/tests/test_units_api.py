"""可抓取单元日历接口 —— GET /api/v1/crawl/units（设计 §1.0）。

前端会议/年份下拉的数据源：断言 9 个组合、实测篇数只给实测过的、
排序从新到旧。不联网 —— 日历是写死在 units.py 的实测结论，不是探活结果。
"""
from conftest import fixture  # noqa: F401  保持与其他测试文件一致的导入风格


def test_units_返回9个单元且从新到旧(client):
    data = client.get("/api/v1/crawl/units").get_json()["data"]
    assert data["total"] == 9
    assert len(data["units"]) == 9

    combos = [(u["conference_code"], u["year"]) for u in data["units"]]
    assert sorted(combos) == sorted([
        ("CVPR", 2022), ("CVPR", 2023), ("CVPR", 2024), ("CVPR", 2025),
        ("CVPR", 2026),
        ("ICCV", 2023), ("ICCV", 2025),
        ("ECCV", 2022), ("ECCV", 2024),
    ])
    # 整体从新到旧（§1.0：用户默认关心最近一届）
    years = [u["year"] for u in data["units"]]
    assert years == sorted(years, reverse=True)


def test_units_实测篇数只给实测过的(client):
    data = client.get("/api/v1/crawl/units").get_json()["data"]
    by_combo = {(u["conference_code"], u["year"]): u for u in data["units"]}

    assert by_combo[("CVPR", 2024)]["expected_papers"] == 2716
    assert by_combo[("ICCV", 2023)]["expected_papers"] == 2156
    assert by_combo[("ECCV", 2024)]["expected_papers"] == 2387
    for combo in (("CVPR", 2024), ("ICCV", 2023), ("ECCV", 2024)):
        assert by_combo[combo]["papers_measured"] is True

    # 没实测的：null + 估值区间，前端算「预计约 X–Y 分钟」用
    for combo in (("CVPR", 2022), ("CVPR", 2026), ("ICCV", 2025), ("ECCV", 2022)):
        unit = by_combo[combo]
        assert unit["expected_papers"] is None
        assert unit["papers_measured"] is False
        assert unit["est_papers_min"] <= unit["est_papers_max"]


def test_units_来源与可用标记(client):
    data = client.get("/api/v1/crawl/units").get_json()["data"]
    by_combo = {(u["conference_code"], u["year"]): u for u in data["units"]}

    assert by_combo[("ECCV", 2024)]["source"] == "ecva"
    assert by_combo[("CVPR", 2024)]["source"] == "cvf"
    assert by_combo[("ICCV", 2023)]["source"] == "cvf"
    assert all(u["available"] for u in data["units"])   # 日历只含实测可抓的
    assert all(u["label"] == f"{u['conference_code']} {u['year']}"
               for u in data["units"])
