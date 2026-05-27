"""
报告生成模块
按固定模板生成日报/周报/月报/年报

===== 计算逻辑说明 =====

【数据来源】
WPS表单 → CSV导出 → reshape_data()解析为长表

【项目总量计算规则】
1. 有子项目的项目（has_sub=True）：
   项目总游客量 = Σ(该项目的所有子项目游客量)
   项目总收入   = Σ(该项目的所有子项目收入)
   特殊：世纪之舟（接待游客）→ 顶层餐厅·观光游客
         世纪之舟（顶层餐厅） → 顶层餐厅·消费游客+收入
         两者合并显示为"顶层餐厅"，但仍计入世纪之舟景区总量

2. 无子项目的项目（has_sub=False）：
   项目总量 = 表单中所有该项目直接填报的数值之和

【板块小计】
板块游客量 = Σ(该板块内所有项目总量游客)
板块收入   = Σ(该板块内所有项目总量收入)

【总计】
总游客量 = Σ(所有板块游客量)
总收入   = Σ(所有板块收入)

【同比/环比】
同比 = (本期值 - 去年同期值) / 去年同期值 × 100%
环比 = (本期值 - 上一期值) / 上一期值 × 100%
仅当去年同期/上一期有数据时显示，否则不显示该比较项

【单位切换】
原始值 < 50 → 使用"人"或"元"
原始值 ≥ 50 → 使用"万人次"或"万元"，保留两位小数

【暂未营业判断】
游客量 == 0 且 收入 == 0 → 显示"暂未营业。"
注意：游客量或收入任一不为0，则正常显示数据

【数据重复检测】
同一日期、同一项目、同一子项目出现≥2条记录 → 标记"数据重复！！！"
"""
from datetime import date, timedelta
import math
import pandas as pd
from config import (
    HIERARCHY, SMALL_VALUE_THRESHOLD,
    CENTURY_BOAT_RULES, DISPLAY_SUB,
)

WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


# ============================================================
# 格式化工具
# ============================================================

def smart_fmt_visitors(raw: float) -> str:
    """
    游客量格式化：
    value < 50 → "X人"
    value ≥ 50 → "X.XX万人次"（四舍五入保留两位小数）
    值为0或NaN → "0万人次"
    """
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return "0万人次"
    raw = float(raw)
    if raw == 0:
        return "0万人次"
    if raw < SMALL_VALUE_THRESHOLD:
        return f"{int(round(raw))}人"
    wan = raw / 10000
    return f"{wan:.2f}万人次"


def smart_fmt_revenue(raw: float) -> str:
    """
    收入格式化：
    value < 50 → "X.XX元"
    value ≥ 50 → "X.XX万元"（四舍五入保留两位小数）
    值为0或NaN → "0万元"
    """
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return "0万元"
    raw = float(raw)
    if raw == 0:
        return "0万元"
    if abs(raw) < SMALL_VALUE_THRESHOLD:
        return f"{raw:.2f}元"
    wan = raw / 10000
    return f"{wan:.2f}万元"


def fmt_pct(cur: float, prev: float, label: str = "同比") -> str:
    """
    变化百分比（保留两位小数）
    cur/prev 任一为0或NaN → 不显示
    """
    if cur is None or prev is None:
        return ""
    try:
        cur_f = float(cur)
        prev_f = float(prev)
    except (ValueError, TypeError):
        return ""
    if math.isnan(cur_f) or math.isnan(prev_f):
        return ""
    if prev_f == 0:
        return ""
    pct = (cur_f - prev_f) / prev_f * 100
    if math.isnan(pct) or math.isinf(pct):
        return ""
    direction = "下降" if pct < 0 else "增长"
    return f"，{label}{direction}{abs(pct):.2f}%"


# ============================================================
# 数据聚合
# ============================================================

def build_data_dict(df: pd.DataFrame) -> dict:
    """
    DataFrame → 嵌套字典分组

    结构: {
      项目显示名: {
        "子项目显示名": {"visitors": N, "revenue": N},
        "_century_guest": {"visitors": N, "revenue": N},  # 世纪之舟·接待游客
        "_century_dine":  {"visitors": N, "revenue": N},  # 世纪之舟·顶层餐厅
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

        # 世纪之舟特殊处理：接待游客→_century_guest, 顶层餐厅→_century_dine
        if row.get("is_century_guest"):
            if "_century_guest" not in result[proj]:
                result[proj]["_century_guest"] = {"visitors": 0, "revenue": 0}
            result[proj]["_century_guest"]["visitors"] += v
            result[proj]["_century_guest"]["revenue"] += r
            continue

        if row.get("is_century_dine"):
            if "_century_dine" not in result[proj]:
                result[proj]["_century_dine"] = {"visitors": 0, "revenue": 0}
            result[proj]["_century_dine"]["visitors"] += v
            result[proj]["_century_dine"]["revenue"] += r
            continue

        key = sub if sub else "_self"
        if key not in result[proj]:
            result[proj][key] = {"visitors": 0, "revenue": 0}
        result[proj][key]["visitors"] += v
        result[proj][key]["revenue"] += r

    return result


def get_project_sum(data: dict, proj_display: str, proj_info: dict) -> dict:
    """
    项目总量 = 所有子项目之和（含世纪之舟特殊子项）
    无子项目的独立项目：对所有非_开头的key求和
    """
    pd_data = data.get(proj_display, {})
    total_v = 0.0
    total_r = 0.0

    if proj_info.get("has_sub"):
        for sub_name in proj_info.get("sub_projects", []):
            lookup_key = DISPLAY_SUB.get(sub_name, sub_name)
            if lookup_key is None:
                continue
            sd = pd_data.get(lookup_key, {"visitors": 0, "revenue": 0})
            total_v += sd.get("visitors", 0) or 0
            total_r += sd.get("revenue", 0) or 0

        cg = pd_data.get("_century_guest", {})
        cd = pd_data.get("_century_dine", {})
        total_v += (cg.get("visitors", 0) or 0) + (cd.get("visitors", 0) or 0)
        total_r += (cg.get("revenue", 0) or 0) + (cd.get("revenue", 0) or 0)
    else:
        if "_self" in pd_data:
            total_v = pd_data["_self"].get("visitors", 0) or 0
            total_r = pd_data["_self"].get("revenue", 0) or 0
        else:
            for key, val in pd_data.items():
                if not key.startswith("_"):
                    total_v += val.get("visitors", 0) or 0
                    total_r += val.get("revenue", 0) or 0

    return {"visitors": total_v, "revenue": total_r}


# ============================================================
# 子项目渲染
# ============================================================

def render_sub_items(proj_data: dict, proj_info: dict) -> str:
    """渲染子项目列表"""
    sub_projects = proj_info.get("sub_projects", [])
    if not sub_projects:
        return ""

    is_century = proj_info.get("special") == "century_boat"
    cg = proj_data.get("_century_guest", {})
    cd = proj_data.get("_century_dine", {})

    skip_subs = set()
    if is_century:
        skip_subs = {CENTURY_BOAT_RULES["guest_sub"],
                     CENTURY_BOAT_RULES["dine_sub"]}

    parts = []

    for sub_name in sub_projects:
        if sub_name in skip_subs:
            continue

        lookup_key = DISPLAY_SUB.get(sub_name, sub_name)
        sd = proj_data.get(lookup_key, {"visitors": 0, "revenue": 0})
        sv = sd.get("visitors", 0) or 0
        sr = sd.get("revenue", 0) or 0

        display_name = DISPLAY_SUB.get(sub_name) or sub_name

        if sv == 0 and sr == 0:
            parts.append(f"{display_name}暂未营业")
        else:
            parts.append(
                f"{display_name}接待游客{smart_fmt_visitors(sv)}，"
                f"实现收入{smart_fmt_revenue(sr)}"
            )

    # 世纪之舟：统一输出顶层餐厅
    if is_century:
        gv = (cg.get("visitors", 0) or 0)
        dv = (cd.get("visitors", 0) or 0)
        dr = (cd.get("revenue", 0) or 0)
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
                          prev_df: pd.DataFrame = None,
                          selected_projects: set = None) -> str:
    data = build_data_dict(df)
    prev_data = build_data_dict(prev_df) if prev_df is not None and len(prev_df) > 0 else {}

    lines = [
        f"【日报】",
        f"{report_date.strftime('%Y年%m月%d日')}，{WEEKDAY_CN[report_date.weekday()]}。"
    ]

    all_v, all_r = 0.0, 0.0

    for plate_key, plate_info in HIERARCHY.items():
        pv_total, pr_total = 0.0, 0.0
        plate_has_content = False

        for proj_key, proj_info in plate_info["projects"].items():
            proj_disp = proj_info["display"]

            # 如果用户指定了项目筛选，只显示选中的
            if selected_projects and proj_disp not in selected_projects:
                continue

            pt = get_project_sum(data, proj_disp, proj_info)
            pp = get_project_sum(prev_data, proj_disp, proj_info)
            v, r = pt["visitors"], pt["revenue"]
            pv, pr_prev = pp["visitors"], pp["revenue"]

            pv_total += v
            pr_total += r
            plate_has_content = True

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

        # 板块小计：仅当该板块有选中项目时显示
        if plate_has_content:
            lines.append(
                f"【{plate_info['subtotal']}】接待游客{smart_fmt_visitors(pv_total)}，"
                f"实现收入{smart_fmt_revenue(pr_total)}。"
            )
            all_v += pv_total
            all_r += pr_total
            lines.append("")

    prev_all_v = sum(
        get_project_sum(prev_data, pi["display"], pi).get("visitors", 0) or 0
        for plate in HIERARCHY.values()
        for pi in plate["projects"].values()
    )
    prev_all_r = sum(
        get_project_sum(prev_data, pi["display"], pi).get("revenue", 0) or 0
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
                           prev_df: pd.DataFrame = None,
                           selected_projects: set = None) -> str:
    data = build_data_dict(df)
    prev_data = build_data_dict(prev_df) if prev_df is not None and len(prev_df) > 0 else {}

    iso = start_date.isocalendar()
    lines = [
        f"【周报】",
        f"{iso[0]}年第{iso[1]}周，{start_date.strftime('%m月%d日')}-{end_date.strftime('%m月%d日')}。"
    ]

    all_v, all_r = 0.0, 0.0

    for plate_key, plate_info in HIERARCHY.items():
        pv_total, pr_total = 0.0, 0.0
        plate_has_content = False

        for proj_key, proj_info in plate_info["projects"].items():
            proj_disp = proj_info["display"]
            if selected_projects and proj_disp not in selected_projects:
                continue

            pt = get_project_sum(data, proj_disp, proj_info)
            v, r = pt["visitors"], pt["revenue"]

            pv_total += v
            pr_total += r
            plate_has_content = True

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

        if plate_has_content:
            lines.append(
                f"【{plate_info['subtotal']}】接待游客{smart_fmt_visitors(pv_total)}，"
                f"实现收入{smart_fmt_revenue(pr_total)}。"
            )
            all_v += pv_total
            all_r += pr_total
            lines.append("")

    prev_all_v = sum(
        get_project_sum(prev_data, pi["display"], pi).get("visitors", 0) or 0
        for plate in HIERARCHY.values()
        for pi in plate["projects"].values()
    )
    prev_all_r = sum(
        get_project_sum(prev_data, pi["display"], pi).get("revenue", 0) or 0
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
# 月报 / 年报
# ============================================================

def generate_monthly_report(df: pd.DataFrame, report_month: date,
                            prev_df: pd.DataFrame = None,
                            selected_projects: set = None) -> str:
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

    all_v, all_r = 0.0, 0.0

    for plate_key, plate_info in HIERARCHY.items():
        pv_total, pr_total = 0.0, 0.0
        plate_has_content = False

        for proj_key, proj_info in plate_info["projects"].items():
            proj_disp = proj_info["display"]
            if selected_projects and proj_disp not in selected_projects:
                continue

            pt = get_project_sum(data, proj_disp, proj_info)
            v, r = pt["visitors"], pt["revenue"]
            pv_total += v
            pr_total += r
            plate_has_content = True

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

        if plate_has_content:
            lines.append(
                f"【{plate_info['subtotal']}】接待游客{smart_fmt_visitors(pv_total)}，"
                f"实现收入{smart_fmt_revenue(pr_total)}。"
            )
            all_v += pv_total
            all_r += pr_total
            lines.append("")

    prev_all_v = sum(
        get_project_sum(prev_data, pi["display"], pi).get("visitors", 0) or 0
        for plate in HIERARCHY.values()
        for pi in plate["projects"].values()
    )
    prev_all_r = sum(
        get_project_sum(prev_data, pi["display"], pi).get("revenue", 0) or 0
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


def generate_yearly_report(df: pd.DataFrame, report_year: int,
                           prev_df: pd.DataFrame = None,
                           selected_projects: set = None) -> str:
    data = build_data_dict(df)
    prev_data = build_data_dict(prev_df) if prev_df is not None and len(prev_df) > 0 else {}

    lines = [f"【年报】", f"{report_year}年度。"]

    all_v, all_r = 0.0, 0.0

    for plate_key, plate_info in HIERARCHY.items():
        pv_total, pr_total = 0.0, 0.0
        plate_has_content = False

        for proj_key, proj_info in plate_info["projects"].items():
            proj_disp = proj_info["display"]
            if selected_projects and proj_disp not in selected_projects:
                continue

            pt = get_project_sum(data, proj_disp, proj_info)
            v, r = pt["visitors"], pt["revenue"]
            pv_total += v
            pr_total += r
            plate_has_content = True

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

        if plate_has_content:
            lines.append(
                f"【{plate_info['subtotal']}】接待游客{smart_fmt_visitors(pv_total)}，"
                f"实现收入{smart_fmt_revenue(pr_total)}。"
            )
            all_v += pv_total
            all_r += pr_total
            lines.append("")

    prev_all_v = sum(
        get_project_sum(prev_data, pi["display"], pi).get("visitors", 0) or 0
        for plate in HIERARCHY.values()
        for pi in plate["projects"].values()
    )
    prev_all_r = sum(
        get_project_sum(prev_data, pi["display"], pi).get("revenue", 0) or 0
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
                    prev_df: pd.DataFrame = None,
                    selected_projects: set = None) -> str:
    if report_type == "daily":
        return generate_daily_report(df, target_date, prev_df, selected_projects)
    elif report_type == "weekly":
        wd = target_date.weekday()
        start = target_date - timedelta(days=wd)
        end = start + timedelta(days=6)
        return generate_weekly_report(df, start, end, prev_df, selected_projects)
    elif report_type == "monthly":
        return generate_monthly_report(df, target_date, prev_df, selected_projects)
    elif report_type == "yearly":
        return generate_yearly_report(df, target_date.year, prev_df, selected_projects)
    return f"Unknown report type: {report_type}"
