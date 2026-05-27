"""
报告生成模块
按固定模板生成日报/周报/月报/年报
"""
from datetime import date, timedelta
import pandas as pd
from config import (
    HIERARCHY, SMALL_VALUE_THRESHOLD,
    CENTURY_BOAT_RULES, DISPLAY_SUB,
)

WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


# ============================================================
# 智能单位格式化
# ============================================================

def smart_fmt_visitors(raw: float) -> str:
    """
    游客量智能格式化：
    原始值 < 50 → "X人"
    原始值 >= 50 → "X.XX万人次"（保留两位小数）
    """
    if raw == 0:
        return "0万人次"
    if raw < SMALL_VALUE_THRESHOLD:
        return f"{int(round(raw))}人"
    wan = raw / 10000
    return f"{wan:.2f}万人次"


def smart_fmt_revenue(raw: float) -> str:
    """
    收入智能格式化：
    原始值 < 50 → "X元"
    原始值 >= 50 → "X.XX万元"
    """
    if raw == 0:
        return "0万元"
    if abs(raw) < SMALL_VALUE_THRESHOLD:
        return f"{raw:.2f}元"
    wan = raw / 10000
    return f"{wan:.2f}万元"


# 旧版兼容
fmt_v = smart_fmt_visitors
fmt_r = smart_fmt_revenue


def fmt_pct(cur: float, prev: float, label: str = "同比") -> str:
    """变化百分比"""
    if prev == 0 or cur == 0:
        return ""
    pct = (cur - prev) / prev * 100
    direction = "下降" if pct < 0 else "增长"
    return f"，{label}{direction}{abs(pct):.2f}%"


# ============================================================
# 数据聚合
# ============================================================

def build_data_dict(df: pd.DataFrame) -> dict:
    """
    DataFrame → 嵌套字典
    {
      project_display: {
        sub_name: {"visitors": N, "revenue": N},
        ...,
        # 世纪之舟特殊字段
        "_century_guest": {"visitors": N},   # 接待游客→观光游客
        "_century_dine": {"visitors": N, "revenue": N},  # 顶层餐厅→消费游客
      }
    }
    """
    result = {}
    for _, row in df.iterrows():
        proj = row["project"]
        sub = row.get("sub_project")
        v = row.get("visitors", 0) or 0
        r = row.get("revenue", 0) or 0

        if proj not in result:
            result[proj] = {}

        # 世纪之舟特殊处理
        if row.get("is_century_guest"):
            if "_century_guest" not in result[proj]:
                result[proj]["_century_guest"] = {"visitors": 0, "revenue": 0}
            result[proj]["_century_guest"]["visitors"] += v
            result[proj]["_century_guest"]["revenue"] += r
            continue  # 不计入普通聚合

        if row.get("is_century_dine"):
            if "_century_dine" not in result[proj]:
                result[proj]["_century_dine"] = {"visitors": 0, "revenue": 0}
            result[proj]["_century_dine"]["visitors"] += v
            result[proj]["_century_dine"]["revenue"] += r
            continue  # 不计入普通聚合

        # 普通子项目聚合
        key = sub if sub else "_self"
        if key not in result[proj]:
            result[proj][key] = {"visitors": 0, "revenue": 0}
        result[proj][key]["visitors"] += v
        result[proj][key]["revenue"] += r

    return result


def get_project_sum(data: dict, proj_display: str, proj_info: dict) -> dict:
    """
    计算项目总量 = 所有子项目之和（含特殊子项）
    """
    pd_data = data.get(proj_display, {})
    total_v = 0
    total_r = 0

    if proj_info.get("has_sub"):
        # 有子项目：遍历子项目列表求和（key需用DISPLAY_SUB映射后的名称）
        for sub_name in proj_info.get("sub_projects", []):
            lookup_key = DISPLAY_SUB.get(sub_name, sub_name)
            if lookup_key is None:
                continue  # 世纪之舟特殊子项，由century flag处理
            sd = pd_data.get(lookup_key, {"visitors": 0, "revenue": 0})
            total_v += sd["visitors"]
            total_r += sd["revenue"]

        # 世纪之舟：加上特殊子项（观光游客 + 消费游客）
        cg = pd_data.get("_century_guest", {})
        cd = pd_data.get("_century_dine", {})
        total_v += cg.get("visitors", 0) + cd.get("visitors", 0)
        total_r += cg.get("revenue", 0) + cd.get("revenue", 0)
    else:
        # 无子项目：取 _self 或从所有key求和
        if "_self" in pd_data:
            total_v = pd_data["_self"]["visitors"]
            total_r = pd_data["_self"]["revenue"]
        else:
            for key, val in pd_data.items():
                if not key.startswith("_"):
                    total_v += val["visitors"]
                    total_r += val["revenue"]

    return {"visitors": total_v, "revenue": total_r}


# ============================================================
# 子项目渲染
# ============================================================

def render_sub_items(proj_data: dict, proj_info: dict) -> str:
    """渲染子项目列表（世纪之舟有特殊处理）"""
    sub_projects = proj_info.get("sub_projects", [])
    if not sub_projects:
        return ""

    is_century = proj_info.get("special") == "century_boat"
    cg = proj_data.get("_century_guest", {})
    cd = proj_data.get("_century_dine", {})

    # 世纪之舟跳过的那两个特殊子项key
    skip_subs = set()
    if is_century:
        skip_subs = {
            CENTURY_BOAT_RULES["guest_sub"],
            CENTURY_BOAT_RULES["dine_sub"],
        }

    parts = []

    for sub_name in sub_projects:
        if sub_name in skip_subs:
            continue  # 世纪之舟特殊子项，后面统一处理

        # 查找数据时应用DISPLAY_SUB映射（表单名→输出名）
        lookup_key = DISPLAY_SUB.get(sub_name, sub_name)
        sd = proj_data.get(lookup_key, {"visitors": 0, "revenue": 0})
        sv, sr = sd["visitors"], sd["revenue"]

        # 显示名 = 映射后的名称（如果映射存在就用映射，否则用原名）
        display_name = DISPLAY_SUB.get(sub_name) or sub_name

        if sv == 0 and sr == 0:
            parts.append(f"{display_name}暂未营业")
        else:
            parts.append(
                f"{display_name}接待游客{smart_fmt_visitors(sv)}，"
                f"实现收入{smart_fmt_revenue(sr)}"
            )

    # 世纪之舟：统一输出顶层餐厅（观光游客 + 消费游客 + 收入）
    if is_century:
        gv = cg.get("visitors", 0)
        dv = cd.get("visitors", 0)
        dr = cd.get("revenue", 0)
        if gv == 0 and dv == 0 and dr == 0:
            parts.insert(0, "顶层餐厅暂未营业")
        else:
            parts.insert(0,
                f"顶层餐厅接待观光游客{smart_fmt_visitors(gv)}，"
                f"接待消费游客{smart_fmt_visitors(dv)}，"
                f"实现收入{smart_fmt_revenue(dr)}"
            )

    return "其中：" + "。".join(parts) + "。" if parts else ""


# ============================================================
# 日报
# ============================================================

def generate_daily_report(df: pd.DataFrame, report_date: date,
                          prev_df: pd.DataFrame = None) -> str:
    data = build_data_dict(df)
    prev_data = build_data_dict(prev_df) if prev_df is not None and len(prev_df) > 0 else {}

    lines = [
        f"【日报】",
        f"{report_date.strftime('%Y年%m月%d日')}，{WEEKDAY_CN[report_date.weekday()]}。"
    ]

    all_v, all_r = 0, 0

    for plate_key, plate_info in HIERARCHY.items():
        pv_total, pr_total = 0, 0

        for proj_key, proj_info in plate_info["projects"].items():
            proj_disp = proj_info["display"]
            pt = get_project_sum(data, proj_disp, proj_info)
            pp = get_project_sum(prev_data, proj_disp, proj_info)
            v, r = pt["visitors"], pt["revenue"]
            pv, pr_prev = pp["visitors"], pp["revenue"]

            pv_total += v
            pr_total += r

            # 暂未营业
            if v == 0 and r == 0:
                lines.append(f"【{proj_disp}】暂未营业。")
                continue

            lines.append(
                f"【{proj_disp}】共接待游客{smart_fmt_visitors(v)}"
                f"{fmt_pct(v, pv, '同比')}。"
                f"实现收入{smart_fmt_revenue(r)}"
                f"{fmt_pct(r, pr_prev, '同比')}。"
            )

            if proj_info.get("has_sub"):
                sub_text = render_sub_items(data.get(proj_disp, {}), proj_info)
                if sub_text:
                    lines.append(sub_text)

        lines.append(
            f"【{plate_info['subtotal']}】接待游客{smart_fmt_visitors(pv_total)}，"
            f"实现收入{smart_fmt_revenue(pr_total)}。"
        )
        all_v += pv_total
        all_r += pr_total
        lines.append("")

    # 总计
    prev_all_v = sum(
        get_project_sum(prev_data, pi["display"], pi).get("visitors", 0)
        for plate in HIERARCHY.values()
        for pi in plate["projects"].values()
    )
    prev_all_r = sum(
        get_project_sum(prev_data, pi["display"], pi).get("revenue", 0)
        for plate in HIERARCHY.values()
        for pi in plate["projects"].values()
    )

    lines.append(
        f"总游客量{smart_fmt_visitors(all_v)}"
        f"{fmt_pct(all_v, prev_all_v, '环比昨日') if prev_all_v > 0 else ''}。"
        f"各业态收入合计{smart_fmt_revenue(all_r)}"
        f"{fmt_pct(all_r, prev_all_r, '环比昨日') if prev_all_r > 0 else ''}。"
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
    lines = [
        f"【周报】",
        f"{iso[0]}年第{iso[1]}周，{start_date.strftime('%m月%d日')}-{end_date.strftime('%m月%d日')}。"
    ]

    all_v, all_r = 0, 0

    for plate_key, plate_info in HIERARCHY.items():
        pv_total, pr_total = 0, 0

        for proj_key, proj_info in plate_info["projects"].items():
            proj_disp = proj_info["display"]
            pt = get_project_sum(data, proj_disp, proj_info)
            v, r = pt["visitors"], pt["revenue"]
            pv_total += v
            pr_total += r

            if v == 0 and r == 0:
                lines.append(f"【{proj_disp}】暂未营业。")
                continue

            lines.append(
                f"【{proj_disp}】共接待游客{smart_fmt_visitors(v)}，"
                f"实现收入{smart_fmt_revenue(r)}。"
            )

            if proj_info.get("has_sub"):
                sub_text = render_sub_items(data.get(proj_disp, {}), proj_info)
                if sub_text:
                    lines.append(sub_text)

        lines.append(
            f"【{plate_info['subtotal']}】接待游客{smart_fmt_visitors(pv_total)}，"
            f"实现收入{smart_fmt_revenue(pr_total)}。"
        )
        all_v += pv_total
        all_r += pr_total
        lines.append("")

    prev_all_v = sum(
        get_project_sum(prev_data, pi["display"], pi).get("visitors", 0)
        for plate in HIERARCHY.values()
        for pi in plate["projects"].values()
    )
    prev_all_r = sum(
        get_project_sum(prev_data, pi["display"], pi).get("revenue", 0)
        for plate in HIERARCHY.values()
        for pi in plate["projects"].values()
    )

    lines.append(
        f"总客流量{smart_fmt_visitors(all_v)}，"
        f"较上周{smart_fmt_visitors(prev_all_v)}"
        f"{fmt_pct(all_v, prev_all_v, '环比') if prev_all_v > 0 else ''}；"
        f"总收入{smart_fmt_revenue(all_r)}，"
        f"较上周{smart_fmt_revenue(prev_all_r)}"
        f"{fmt_pct(all_r, prev_all_r, '环比') if prev_all_r > 0 else ''}。"
    )
    lines.append("【市文旅集团】")
    return "\n".join(lines)


# ============================================================
# 月报
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

    lines = [
        f"【月报】",
        f"{report_month.strftime('%Y年%m月')}，{start.strftime('%m月%d日')}-{end.strftime('%m月%d日')}。"
    ]

    all_v, all_r = 0, 0

    for plate_key, plate_info in HIERARCHY.items():
        pv_total, pr_total = 0, 0

        for proj_key, proj_info in plate_info["projects"].items():
            proj_disp = proj_info["display"]
            pt = get_project_sum(data, proj_disp, proj_info)
            v, r = pt["visitors"], pt["revenue"]
            pv_total += v
            pr_total += r

            if v == 0 and r == 0:
                lines.append(f"【{proj_disp}】暂未营业。")
                continue

            lines.append(
                f"【{proj_disp}】共接待游客{smart_fmt_visitors(v)}，"
                f"实现收入{smart_fmt_revenue(r)}。"
            )
            if proj_info.get("has_sub"):
                sub_text = render_sub_items(data.get(proj_disp, {}), proj_info)
                if sub_text:
                    lines.append(sub_text)

        lines.append(
            f"【{plate_info['subtotal']}】接待游客{smart_fmt_visitors(pv_total)}，"
            f"实现收入{smart_fmt_revenue(pr_total)}。"
        )
        all_v += pv_total
        all_r += pr_total
        lines.append("")

    prev_all_v = sum(
        get_project_sum(prev_data, pi["display"], pi).get("visitors", 0)
        for plate in HIERARCHY.values()
        for pi in plate["projects"].values()
    )
    prev_all_r = sum(
        get_project_sum(prev_data, pi["display"], pi).get("revenue", 0)
        for plate in HIERARCHY.values()
        for pi in plate["projects"].values()
    )

    lines.append(
        f"总客流量{smart_fmt_visitors(all_v)}"
        f"{fmt_pct(all_v, prev_all_v, '环比') if prev_all_v > 0 else ''}；"
        f"总收入{smart_fmt_revenue(all_r)}"
        f"{fmt_pct(all_r, prev_all_r, '环比') if prev_all_r > 0 else ''}。"
    )
    lines.append("【市文旅集团】")
    return "\n".join(lines)


# ============================================================
# 年报
# ============================================================

def generate_yearly_report(df: pd.DataFrame, report_year: int,
                           prev_df: pd.DataFrame = None) -> str:
    data = build_data_dict(df)
    prev_data = build_data_dict(prev_df) if prev_df is not None and len(prev_df) > 0 else {}

    lines = [f"【年报】", f"{report_year}年度。"]

    all_v, all_r = 0, 0

    for plate_key, plate_info in HIERARCHY.items():
        pv_total, pr_total = 0, 0

        for proj_key, proj_info in plate_info["projects"].items():
            proj_disp = proj_info["display"]
            pt = get_project_sum(data, proj_disp, proj_info)
            v, r = pt["visitors"], pt["revenue"]
            pv_total += v
            pr_total += r

            if v == 0 and r == 0:
                lines.append(f"【{proj_disp}】暂未营业。")
                continue

            lines.append(
                f"【{proj_disp}】共接待游客{smart_fmt_visitors(v)}，"
                f"实现收入{smart_fmt_revenue(r)}。"
            )
            if proj_info.get("has_sub"):
                sub_text = render_sub_items(data.get(proj_disp, {}), proj_info)
                if sub_text:
                    lines.append(sub_text)

        lines.append(
            f"【{plate_info['subtotal']}】接待游客{smart_fmt_visitors(pv_total)}，"
            f"实现收入{smart_fmt_revenue(pr_total)}。"
        )
        all_v += pv_total
        all_r += pr_total
        lines.append("")

    prev_all_v = sum(
        get_project_sum(prev_data, pi["display"], pi).get("visitors", 0)
        for plate in HIERARCHY.values()
        for pi in plate["projects"].values()
    )
    prev_all_r = sum(
        get_project_sum(prev_data, pi["display"], pi).get("revenue", 0)
        for plate in HIERARCHY.values()
        for pi in plate["projects"].values()
    )

    lines.append(
        f"全年总客流量{smart_fmt_visitors(all_v)}"
        f"{fmt_pct(all_v, prev_all_v, '同比') if prev_all_v > 0 else ''}；"
        f"全年总收入{smart_fmt_revenue(all_r)}"
        f"{fmt_pct(all_r, prev_all_r, '同比') if prev_all_r > 0 else ''}。"
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
    return f"Unknown report type: {report_type}"
