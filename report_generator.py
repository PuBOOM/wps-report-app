"""
报告生成模块
根据聚合数据 + 配置，按固定模板生成日报/周报/月报/年报
"""
from datetime import date, timedelta
import pandas as pd
from config import (
    HIERARCHY, VISITOR_UNIT_DIVISOR, REVENUE_UNIT_DIVISOR
)

WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def fmt_v(v: float) -> str:
    """格式化游客量：万人次，去尾零"""
    val = v / VISITOR_UNIT_DIVISOR
    if val == 0:
        return "0"
    s = f"{val:.4f}".rstrip("0").rstrip(".")
    return s


def fmt_r(v: float) -> str:
    """格式化收入：万元，保留2位小数"""
    return f"{v / REVENUE_UNIT_DIVISOR:.2f}"


def fmt_yoy(cur: float, prev: float) -> str:
    """同比下降"""
    if prev == 0:
        return "" if cur == 0 else ""
    pct = (cur - prev) / prev * 100
    return f"，同比下降{abs(pct):.2f}%" if pct < 0 else f"，同比增长{pct:.2f}%"


def fmt_qoq(cur: float, prev: float) -> str:
    """环比变化"""
    if prev == 0:
        return ""
    pct = (cur - prev) / prev * 100
    return f"，环比下降{abs(pct):.2f}%" if pct < 0 else f"，环比上升{pct:.2f}%"


def build_data_dict(df: pd.DataFrame) -> dict:
    """
    DataFrame → 嵌套字典
    {
      project: {
        "_total": {"visitors": N, "revenue": N},  # 不含 __guest_total__
        "_guest": {"visitors": N, "revenue": N},   # 仅世纪之舟（接待游客）
        sub_name: {"visitors": N, "revenue": N},
        ...
      }
    }
    """
    result = {}
    for _, row in df.iterrows():
        proj = row["project"]
        sub = row.get("sub_project")
        is_guest = row.get("is_guest_total", False)
        v = row.get("visitors", 0) or 0
        r = row.get("revenue", 0) or 0

        if proj not in result:
            result[proj] = {"_total": {"visitors": 0, "revenue": 0},
                            "_guest": {"visitors": 0, "revenue": 0}}

        if is_guest and sub == "__guest_total__":
            # 世纪之舟（接待游客）→ 归入_guest
            result[proj]["_guest"]["visitors"] += v
            result[proj]["_guest"]["revenue"] += r
        else:
            result[proj]["_total"]["visitors"] += v
            result[proj]["_total"]["revenue"] += r

        # 子项目明细（不包含 __guest_total__）
        if sub and sub != "__guest_total__":
            key = sub
            if key not in result[proj]:
                result[proj][key] = {"visitors": 0, "revenue": 0}
            result[proj][key]["visitors"] += v
            result[proj][key]["revenue"] += r

    return result


def get_project_total(data: dict, proj_display: str) -> dict:
    """获取项目总量：_guest优先（世纪之舟接待游客），否则_totalsum"""
    pd_data = data.get(proj_display, {})
    guest = pd_data.get("_guest", {"visitors": 0, "revenue": 0})
    total = pd_data.get("_total", {"visitors": 0, "revenue": 0})

    visitors = guest["visitors"] if guest["visitors"] > 0 else total["visitors"]
    revenue = total["revenue"]  # revenue always from sum (guest entry has revenue=0)
    # 但如果 guest 有revenue，用guest的
    if guest["revenue"] > 0:
        revenue = guest["revenue"]

    return {"visitors": visitors, "revenue": revenue}


def render_sub_items(proj_data: dict, proj_info: dict, is_daily: bool = True) -> str:
    """渲染子项目列表"""
    sub_projects = proj_info.get("sub_projects", [])
    if not sub_projects:
        return ""

    parts = []
    for sub_name in sub_projects:
        sd = proj_data.get(sub_name, {"visitors": 0, "revenue": 0})
        sv, sr = sd["visitors"], sd["revenue"]

        special = proj_info.get("special_sub", {}).get(sub_name)
        if special and special.get("type") == "restaurant":
            # 顶层餐厅：表单无观光/消费区分，用总量填充
            parts.append(
                f"{sub_name}接待观光游客{fmt_v(sv)}万人次，"
                f"接待消费游客{fmt_v(sv)}万人次，"
                f"实现收入{fmt_r(sr)}万元"
            )
        elif sv == 0 and sr == 0:
            parts.append(f"{sub_name}暂未营业")
        else:
            parts.append(
                f"{sub_name}接待游客{fmt_v(sv)}万人次，实现收入{fmt_r(sr)}万元"
            )

    return "其中：" + "。".join(parts) + "。" if parts else ""


# ============================================================
# 日报
# ============================================================

def generate_daily_report(df: pd.DataFrame, report_date: date,
                          prev_df: pd.DataFrame = None) -> str:
    data = build_data_dict(df)
    prev_data = build_data_dict(prev_df) if prev_df is not None and len(prev_df) > 0 else {}

    lines = [f"【日报】",
             f"{report_date.strftime('%Y年%m月%d日')}，{WEEKDAY_CN[report_date.weekday()]}。"]

    all_v, all_r = 0, 0
    prev_all_v = sum(get_project_total(prev_data, p).get("visitors", 0)
                     for plate in HIERARCHY.values()
                     for p in [pi["display"] for pi in plate["projects"].values()])
    prev_all_r = sum(get_project_total(prev_data, p).get("revenue", 0)
                     for plate in HIERARCHY.values()
                     for p in [pi["display"] for pi in plate["projects"].values()])

    for plate_key, plate_info in HIERARCHY.items():
        pv_total, pr_total = 0, 0

        for proj_key, proj_info in plate_info["projects"].items():
            proj_disp = proj_info["display"]
            pt = get_project_total(data, proj_disp)
            pp = get_project_total(prev_data, proj_disp)
            v, r = pt["visitors"], pt["revenue"]
            pv, pr = pp["visitors"], pp["revenue"]
            pv_total += v
            pr_total += r

            if proj_info.get("is_closed") and v == 0:
                lines.append(f"【{proj_disp}】暂未营业。")
                continue
            if v == 0 and r == 0:
                lines.append(f"【{proj_disp}】暂未营业。")
                continue

            lines.append(
                f"【{proj_disp}】共接待游客{fmt_v(v)}万人次{fmt_yoy(v, pv)}。"
                f"实现收入{fmt_r(r)}万元{fmt_yoy(r, pr)}。"
            )

            if proj_info.get("has_sub"):
                sub_text = render_sub_items(data.get(proj_disp, {}), proj_info, is_daily=True)
                if sub_text:
                    lines.append(sub_text)

        lines.append(
            f"【{plate_info['subtotal']}】接待游客{fmt_v(pv_total)}万人次，"
            f"实现收入{fmt_r(pr_total)}万元。"
        )
        all_v += pv_total
        all_r += pr_total
        lines.append("")

    lines.append(
        f"总游客量{fmt_v(all_v)}万人次{fmt_qoq(all_v, prev_all_v)}。"
        f"各业态收入合计{fmt_r(all_r)}万元{fmt_qoq(all_r, prev_all_r)}。"
    )
    lines.append("【市文旅集团】")
    return "\n".join(lines)


# ============================================================
# 周报
# ============================================================

def generate_weekly_report(df: pd.DataFrame, start_date: date, end_date: date,
                           prev_df: pd.DataFrame = None) -> str:
    data = build_data_dict(df)
    prev_data = build_data_dict(prev_df) if prev_df is not None and len(prev_df) > 0 else {}

    iso = start_date.isocalendar()
    lines = [f"【周报】",
             f"{iso[0]}年第{iso[1]}周，{start_date.strftime('%m月%d日')}-{end_date.strftime('%m月%d日')}。"]

    all_v, all_r = 0, 0
    prev_all_v = sum(get_project_total(prev_data, p).get("visitors", 0)
                     for plate in HIERARCHY.values()
                     for p in [pi["display"] for pi in plate["projects"].values()])
    prev_all_r = sum(get_project_total(prev_data, p).get("revenue", 0)
                     for plate in HIERARCHY.values()
                     for p in [pi["display"] for pi in plate["projects"].values()])

    for plate_key, plate_info in HIERARCHY.items():
        pv_total, pr_total = 0, 0

        for proj_key, proj_info in plate_info["projects"].items():
            proj_disp = proj_info["display"]
            pt = get_project_total(data, proj_disp)
            v, r = pt["visitors"], pt["revenue"]
            pv_total += v
            pr_total += r

            if proj_info.get("is_closed") and v == 0:
                lines.append(f"【{proj_disp}】暂未营业。")
                continue

            lines.append(
                f"【{proj_disp}】共接待游客{fmt_v(v)}万人次，实现收入{fmt_r(r)}万元。"
            )

            if proj_info.get("has_sub"):
                sub_text = render_sub_items(data.get(proj_disp, {}), proj_info, is_daily=False)
                if sub_text:
                    lines.append(sub_text)

        lines.append(
            f"【{plate_info['subtotal']}】接待游客{fmt_v(pv_total)}万人次，"
            f"实现收入{fmt_r(pr_total)}万元。"
        )
        all_v += pv_total
        all_r += pr_total
        lines.append("")

    prev_v_str = fmt_v(prev_all_v)
    prev_r_str = fmt_r(prev_all_r)
    lines.append(
        f"总客流量{fmt_v(all_v)}万人，"
        f"较上周{prev_v_str}万人{fmt_qoq(all_v, prev_all_v)}；"
        f"总收入{fmt_r(all_r)}万元，"
        f"较上周{prev_r_str}万元{fmt_qoq(all_r, prev_all_r)}。"
    )
    lines.append("【市文旅集团】")
    return "\n".join(lines)


# ============================================================
# 月报 / 年报
# ============================================================

def generate_monthly_report(df: pd.DataFrame, report_month: date,
                            prev_df: pd.DataFrame = None) -> str:
    start = report_month.replace(day=1)
    if report_month.month == 12:
        end = date(report_month.year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(report_month.year, report_month.month + 1, 1) - timedelta(days=1)

    data = build_data_dict(df)
    prev_data = build_data_dict(prev_df) if prev_df is not None and len(prev_df) > 0 else {}

    lines = [f"【月报】",
             f"{report_month.strftime('%Y年%m月')}，{start.strftime('%m月%d日')}-{end.strftime('%m月%d日')}。"]

    all_v, all_r = 0, 0
    prev_all_v = sum(get_project_total(prev_data, p).get("visitors", 0)
                     for plate in HIERARCHY.values()
                     for p in [pi["display"] for pi in plate["projects"].values()])
    prev_all_r = sum(get_project_total(prev_data, p).get("revenue", 0)
                     for plate in HIERARCHY.values()
                     for p in [pi["display"] for pi in plate["projects"].values()])

    for plate_key, plate_info in HIERARCHY.items():
        pv_total, pr_total = 0, 0

        for proj_key, proj_info in plate_info["projects"].items():
            proj_disp = proj_info["display"]
            pt = get_project_total(data, proj_disp)
            v, r = pt["visitors"], pt["revenue"]
            pv_total += v
            pr_total += r

            if proj_info.get("is_closed") and v == 0:
                lines.append(f"【{proj_disp}】暂未营业。")
                continue

            lines.append(
                f"【{proj_disp}】共接待游客{fmt_v(v)}万人次，实现收入{fmt_r(r)}万元。"
            )

            if proj_info.get("has_sub"):
                sub_text = render_sub_items(data.get(proj_disp, {}), proj_info)
                if sub_text:
                    lines.append(sub_text)

        lines.append(
            f"【{plate_info['subtotal']}】接待游客{fmt_v(pv_total)}万人次，"
            f"实现收入{fmt_r(pr_total)}万元。"
        )
        all_v += pv_total
        all_r += pr_total
        lines.append("")

    lines.append(
        f"总客流量{fmt_v(all_v)}万人{fmt_qoq(all_v, prev_all_v)}；"
        f"总收入{fmt_r(all_r)}万元{fmt_qoq(all_r, prev_all_r)}。"
    )
    lines.append("【市文旅集团】")
    return "\n".join(lines)


def generate_yearly_report(df: pd.DataFrame, report_year: int,
                           prev_df: pd.DataFrame = None) -> str:
    data = build_data_dict(df)
    prev_data = build_data_dict(prev_df) if prev_df is not None and len(prev_df) > 0 else {}

    lines = [f"【年报】", f"{report_year}年度。"]

    all_v, all_r = 0, 0
    prev_all_v = sum(get_project_total(prev_data, p).get("visitors", 0)
                     for plate in HIERARCHY.values()
                     for p in [pi["display"] for pi in plate["projects"].values()])
    prev_all_r = sum(get_project_total(prev_data, p).get("revenue", 0)
                     for plate in HIERARCHY.values()
                     for p in [pi["display"] for pi in plate["projects"].values()])

    for plate_key, plate_info in HIERARCHY.items():
        pv_total, pr_total = 0, 0

        for proj_key, proj_info in plate_info["projects"].items():
            proj_disp = proj_info["display"]
            pt = get_project_total(data, proj_disp)
            v, r = pt["visitors"], pt["revenue"]
            pv_total += v
            pr_total += r

            if proj_info.get("is_closed") and v == 0:
                lines.append(f"【{proj_disp}】暂未营业。")
                continue

            lines.append(
                f"【{proj_disp}】共接待游客{fmt_v(v)}万人次，实现收入{fmt_r(r)}万元。"
            )

            if proj_info.get("has_sub"):
                sub_text = render_sub_items(data.get(proj_disp, {}), proj_info)
                if sub_text:
                    lines.append(sub_text)

        lines.append(
            f"【{plate_info['subtotal']}】接待游客{fmt_v(pv_total)}万人次，"
            f"实现收入{fmt_r(pr_total)}万元。"
        )
        all_v += pv_total
        all_r += pr_total
        lines.append("")

    lines.append(
        f"全年总客流量{fmt_v(all_v)}万人次{fmt_yoy(all_v, prev_all_v)}；"
        f"全年总收入{fmt_r(all_r)}万元{fmt_yoy(all_r, prev_all_r)}。"
    )
    lines.append("【市文旅集团】")
    return "\n".join(lines)


# ============================================================
# 统一入口
# ============================================================

def generate_report(df: pd.DataFrame, report_type: str,
                    target_date: date,
                    prev_df: pd.DataFrame = None) -> str:
    if report_type == "daily":
        return generate_daily_report(df, target_date, prev_df)
    elif report_type == "weekly":
        wd = target_date.weekday()
        start = target_date - timedelta(days=wd)
        end = start + timedelta(days=6)
        return generate_weekly_report(df, start, end, prev_df)
    elif report_type == "monthly":
        return generate_monthly_report(df, target_date, prev_df)
    elif report_type == "yearly":
        return generate_yearly_report(df, target_date.year, prev_df)
    return f"不支持的报表类型: {report_type}"
