"""
数据加载与清洗模块
负责解析从WPS表单导出的CSV/Excel文件，重构为标准格式
支持 UTF-8 / GBK / GB2312 编码自动识别
"""
import re
import pandas as pd
from config import (
    FORM_PROJECT_MAP, FORM_SUB_MAP,
    CENTURY_BOAT_GUEST_FLAG
)


def load_csv(file) -> pd.DataFrame:
    """加载CSV或Excel文件，自动识别编码（GBK/UTF-8）"""
    filename = file.name.lower()
    if filename.endswith((".xlsx", ".xls")):
        return pd.read_excel(file)

    raw = file.read()
    import io

    # 策略：直接用GBK读（WPS中文环境默认），验证是否成功
    encodings = ["gbk", "gb18030", "utf-8-sig", "utf-8"]

    for enc in encodings:
        try:
            buf = io.BytesIO(raw)
            df = pd.read_csv(buf, encoding=enc)

            # 验证：检日期列是否存在
            found = False
            for col in df.columns:
                s = str(col)
                if '\u65e5\u671f' in s:  # "日期"
                    found = True
                    break
                if '\u9879\u76ee' in s:  # "项目"
                    found = True
                    break

            if found:
                return df
        except UnicodeDecodeError:
            continue

    # 兜底
    buf = io.BytesIO(raw)
    return pd.read_csv(buf, encoding="utf-8", encoding_errors="replace")


def parse_cascade(value: str) -> dict:
    """
    解析WPS表单3级级联选项
    输入: "乌拉文传公司（文体旅游板块）-松江中路-1917咖啡厅"
    返回: {"plate": "文体旅游板块", "project": "松江中路", "sub_project": "1917咖啡厅"}
    """
    if pd.isna(value) or not value or str(value).strip() == "":
        return {"plate": None, "project": None, "sub_project": None, "is_guest_total": False}

    value = str(value).strip()
    parts = value.split("-", 2)  # 最多分3段

    plate = None
    project = None
    sub_project = None
    is_guest_total = False

    if len(parts) >= 1:
        m = re.search(r"[（(](.*?)[）)]", parts[0])
        if m:
            plate = m.group(1)
        else:
            plate = parts[0]

    if len(parts) >= 2:
        project = parts[1]

    if len(parts) >= 3:
        sub_project = parts[2]
        # 检测是否为"接待游客"类型的总量标记（如"世纪之舟（接待游客）"）
        if CENTURY_BOAT_GUEST_FLAG in sub_project:
            is_guest_total = True

    return {
        "plate": plate,
        "project": project,
        "sub_project": sub_project,
        "is_guest_total": is_guest_total,
    }


def reshape_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    宽表 → 长表重构
    每行一条记录 → 每行一个项目
    """
    rows = []

    # 找日期列
    date_col = None
    # 先尝试Unicode码点匹配（"日期" = U+65E5 U+671F）
    for col in df.columns:
        s = str(col)
        if '\u65e5\u671f' in s:
            date_col = col
            break
    # 兜底：尝试直接字符串匹配
    if date_col is None:
        for col in df.columns:
            if '日期' in str(col):
                date_col = col
                break
    # 英文列名
    if date_col is None:
        for col in df.columns:
            if str(col).lower().strip() == 'date':
                date_col = col
                break
    if date_col is None:
        # 调试输出
        cols_repr = [repr(c) for c in df.columns[:5]]
        raise ValueError(
            f"Date column not found. First 5 cols: {cols_repr}"
        )

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
            is_guest = cascade["is_guest_total"]

            if not plate or not project_raw:
                continue

            # 映射
            project_display = FORM_PROJECT_MAP.get(project_raw, project_raw)
            sub_display = None
            if sub_raw:
                mapped = FORM_SUB_MAP.get(sub_raw)
                if mapped is None and is_guest:
                    # 世纪之舟（接待游客）→ 不显示为子项，而是父项总量
                    sub_display = "__guest_total__"
                elif mapped:
                    sub_display = mapped
                else:
                    sub_display = sub_raw

            # 数值
            try:
                visitor = float(row.get(visitor_col, 0) or 0)
            except (ValueError, TypeError):
                visitor = 0
            try:
                revenue = float(row.get(revenue_col, 0) or 0)
            except (ValueError, TypeError):
                revenue = 0

            rows.append({
                "date": d,
                "plate": plate,
                "project_raw": project_raw,
                "project": project_display,
                "sub_project": sub_display,
                "is_guest_total": is_guest,
                "visitors": visitor,
                "revenue": revenue,
            })

    if not rows:
        return pd.DataFrame(columns=[
            "date", "plate", "project_raw", "project",
            "sub_project", "is_guest_total", "visitors", "revenue"
        ])

    return pd.DataFrame(rows)


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
