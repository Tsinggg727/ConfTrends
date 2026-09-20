"""可抓取单元（会议 × 年份）日历。

对应设计文档 §1.0。三大顶会的举办节奏不同，必须按年份枚举：

    CVPR  每年一届        2022 2023 2024 2025 2026
    ICCV  两年一届（奇数）        2023      2025
    ECCV  两年一届（偶数）  2022      2024

合计 **9 个可抓取单元**（CVPR 5 + ICCV 2 + ECCV 2，实测确认，非估算）。

⚠️ ECCV 2026 截至 2026-09-20 尚未在 ECVA 发布（papers.php 最新只到 2024），
   所以 ECCV 实际是 2022 / 2024 两届。等放榜后在这里加一个数字即可，流程不动。

一个「单元」= 一个独立抓取任务粒度：可单独启动、单独看进度、单独重跑。
"""
from dataclasses import dataclass

from .parsers import cvf, ecva

# 每个会议的可抓年份，以及它挂在哪个源站上
CONFERENCE_UNITS = {
    "CVPR": {"source": cvf.SOURCE, "years": (2022, 2023, 2024, 2025, 2026)},
    "ICCV": {"source": cvf.SOURCE, "years": (2023, 2025)},
    "ECCV": {"source": ecva.SOURCE, "years": (2022, 2024)},
}

CONFERENCE_CODES = tuple(CONFERENCE_UNITS)

# ECVA 列表页没有 BibTeX，booktitle 得自己拼（设计文档 §6.2：可自行拼装或省略）
VENUE_LABELS = {
    "CVPR": "Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)",
    "ICCV": "Proceedings of the IEEE/CVF International Conference on Computer Vision (ICCV)",
    "ECCV": "Proceedings of the European Conference on Computer Vision (ECCV)",
}

# 「不限定会议」时按这个顺序依次找：整体从新到旧，同一年内 CVPR > ICCV > ECCV
_CONF_ORDER = {"CVPR": 0, "ICCV": 1, "ECCV": 2}


@dataclass(frozen=True)
class Unit:
    """一个可抓取单元。"""

    source: str            # cvf / ecva
    conference_code: str   # CVPR / ICCV / ECCV
    year: int
    index_url: str         # 列表页 URL
    tag: str               # 解析器需要的年份标记：CVF 拼在 URL 里，ECVA 用来筛 href
    label: str             # 给人看的，如 "CVPR 2024"

    @property
    def key(self):         # 稳定主键，如 "CVPR2024" / "ECCV2024"
        return f"{self.conference_code}{self.year}"


def build_unit(conference_code, year):
    spec = CONFERENCE_UNITS[conference_code]
    parser = cvf if spec["source"] == cvf.SOURCE else ecva
    if spec["source"] == ecva.SOURCE:
        tag = ecva.year_tag(year)
    else:
        tag = f"{conference_code}{year}"
    return Unit(
        source=spec["source"],
        conference_code=conference_code,
        year=year,
        index_url=parser.index_url(conference_code, year),
        tag=tag,
        label=f"{conference_code} {year}",
    )


def list_units():
    """全部可抓取单元，按「新 → 旧、CVPR → ICCV → ECCV」排序。"""
    units = [
        build_unit(code, year)
        for code, spec in CONFERENCE_UNITS.items()
        for year in spec["years"]
    ]
    return sorted(units, key=lambda u: (-u.year, _CONF_ORDER[u.conference_code]))


def units_for(conference_code=None, year=None):
    """按限定条件取单元列表。

    会议和年份都不给时返回全部 9 个 —— 上层按顺序找，命中即停。
    这也是「用户只记得题目」时唯一能走的路，代价是要依次拉多个索引页。
    """
    units = list_units()
    if conference_code:
        units = [u for u in units if u.conference_code == conference_code]
    if year:
        units = [u for u in units if u.year == year]
    return units


def held_in(conference_code, year):
    """该会议在这一年是否真的办过（用于把参数错误和抓取失败区分开）。"""
    spec = CONFERENCE_UNITS.get(conference_code)
    return bool(spec) and year in spec["years"]
