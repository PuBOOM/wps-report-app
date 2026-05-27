"""
数据加载与清洗模块
解析WPS表单CSV → 标准长表格式
"""
import re
import pandas as pd
from config import (
    DISPLAY_PROJECT, DISPLAY_SUB,
    PROJECT_MERGE_MAP, SUB_MERGE_MAP,
    CENTURY_BOAT_RULES,
)


def load_csv(file) -> pd.DataFrame:
    """加载CSV/Excel，自动识别编码"""
    filename = file.name.lower()
    if filename.endswith((".xlsx", ".xls")):
        return pd.read_excel(file)

    raw = file.read()
    import io

    for enc in ["gbk", "gb18030", "utf-8-sig", "utf-8"]:
        try:
            buf = io.BytesIO(raw)
            df = pd.read_csv(buf, encoding=enc)
            for col in df.columns:
                s = str(col)
                if '\u65e5\u671f' in s or '\u9879\u76ee' in s:
                    return df
        except UnicodeDecodeError:
            continue

    buf = io.BytesIO(raw)
    return pd.read_csv(buf, encoding="utf-8", encoding_errors="replace")


def _safe_float(val) -> float:
    """安全转float，NaN/空值/非数字 → 0"""
    if val is None:
        return 0.0
    try:
        f = float(val)
        if pd.isna(f):
            return 0.0
        return f
    except (ValueError, TypeError):
        return 0.0


def parse_cascade(value: str) -> dict:
    """解析3级级联: "公司（板块）-项目-子项目" """
    if pd.isna(value) or not value or str(value).strip() == "":
        return {"plate": None, "project": None, "sub_project": None}

    value = str(value).strip()
    parts = value.split("-", 2)

    plate = None
    project = None
    sub_project = None

    if len(parts) >= 1:
        m = re.search(r"[（(](.*?)[）)]", parts[0])
        plate = m.group(1) if m else parts[0]
    if len(parts) >= 2:
        project = parts[1]
    if len(parts) >= 3:
        sub_project = parts[2]

    return {"plate": plate, "project": project, "sub_project": sub_project}


def reshape_data(df: pd.DataFrame) -> pd.DataFrame:
    """宽表 → 长表，同时做项目合并和名称映射"""
    rows = []

    date_col = None
    for col in df.columns:
        s = str(col)
        if '\u65e5\u671f' in s:
            date_col = col
            break
    if date_col is None:
        raise ValueError(f"Date column not found. Columns: {list(df.columns[:5])}")

    for _, row in df.iterrows():
        date_val = row.get(date_col)
        if pd.isna(date_val):
            continue
        try:
            d = pd.to_datetime(date_val).date()
        except Exception:
            continue

        for i in range(1, 5):
            name_col = f"项目名称{i}"
            visitor_col = f"游客量{i}"
            revenue_col = f"收入{i}"

            if name_col not in df.columns:
                continue

            name_val = row.get(name_col)
            if pd.isna(name_val) or str(name_val).strip() == "":
                continue

            cascade = parse_cascade(name_val)
            plate = cascade["plate"]
            project_raw = cascade["project"]
            sub_raw = cascade["sub_project"]

            if not plate or not project_raw:
                continue

            # ---- 合并规则 ----
            project_merged = PROJECT_MERGE_MAP.get(project_raw, project_raw)

            if sub_raw:
                sub_merged = SUB_MERGE_MAP.get(sub_raw, sub_raw)
            else:
                sub_merged = None

            # ---- 输出端名称映射 ----
            project_display = DISPLAY_PROJECT.get(project_merged, project_merged)
            sub_display = DISPLAY_SUB.get(sub_merged, sub_merged) if sub_merged else None

            # ---- 世纪之舟特殊标记 ----
            is_century_guest = (
                project_merged == "世纪之舟"
                and sub_raw == CENTURY_BOAT_RULES["guest_sub"]
            )
            is_century_dine = (
                project_merged == "世纪之舟"
                and sub_raw == CENTURY_BOAT_RULES["dine_sub"]
            )
            is_century_boat = (project_merged == "世纪之舟")

            # 数值（修复NaN问题）
            visitor = _safe_float(row.get(visitor_col))
            revenue = _safe_float(row.get(revenue_col))

            # 世纪之舟特殊子项：分配独立sub_project值，避免重复检测误报
            if is_century_guest:
                sub_display = "__century_guest__"
            elif is_century_dine:
                sub_display = "__century_dine__"

            rows.append({
                "date": d,
                "plate": plate,
                "project_raw": project_raw,
                "project": project_display,
                "sub_project": sub_display,
                "is_century_guest": is_century_guest,
                "is_century_dine": is_century_dine,
                "is_century_boat": is_century_boat,
                "visitors": visitor,
                "revenue": revenue,
            })

    if not rows:
        return pd.DataFrame(columns=[
            "date", "plate", "project_raw", "project",
            "sub_project", "is_century_guest", "is_century_dine",
            "is_century_boat", "visitors", "revenue"
        ])
    return pd.DataFrame(rows)


def find_duplicates(df: pd.DataFrame) -> list:
    """
    检测同一日期、同一项目+子项目是否有重复数据
    返回重复信息列表: [(date, project, sub_project, count), ...]
    """
    dup_info = []

    grouped = df.groupby(["date", "project", "sub_project"], dropna=False)
    for (d, proj, sub), group in grouped:
        cnt = len(group)
        if cnt > 1:
            # 排除世纪之舟内部标记
            sub_str = str(sub) if sub else "(无子项目)"
            if sub_str.startswith("__century"):
                sub_str = "顶层餐厅特殊数据"
            dup_info.append((d, proj, sub_str, cnt))

    return dup_info


def filter_by_date(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    return df[(df["date"] >= start_date) & (df["date"] <= end_date)]


def filter_by_plates(df: pd.DataFrame, plates: list) -> pd.DataFrame:
    if not plates:
        return df
    return df[df["plate"].isin(plates)]


def filter_by_projects(df: pd.DataFrame, projects: list) -> pd.DataFrame:
    if not projects:
        return df
    return df[df["project"].isin(projects)]
