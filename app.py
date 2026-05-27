"""
日报/周报/月报/年报 — 查询汇总生成系统
数据来源：WPS表单导出CSV → 自动解析 → 格式化输出
"""
import streamlit as st
import pandas as pd
from datetime import date, timedelta
import html

from config import HIERARCHY
from data_loader import load_csv, reshape_data, filter_by_date, filter_by_plates, filter_by_projects
from report_generator import generate_report


# ---- 页面设置 ----
st.set_page_config(
    page_title="文旅集团数据查询系统",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📊 文旅集团 — 数据查询汇总系统")
st.caption("每日从WPS表单导出CSV → 上传 → 一键生成日报/周报/月报/年报")


# ---- Session State 初始化 ----
if "data" not in st.session_state:
    st.session_state.data = None
if "report" not in st.session_state:
    st.session_state.report = ""
if "report_type" not in st.session_state:
    st.session_state.report_type = "日报"
if "target_date" not in st.session_state:
    st.session_state.target_date = date.today()
if "current_df" not in st.session_state:
    st.session_state.current_df = pd.DataFrame()


# ============================================================
# 侧边栏：数据上传 & 查询设置
# ============================================================

with st.sidebar:
    st.header("📁 数据上传")

    uploaded_file = st.file_uploader(
        "从WPS导出CSV/Excel上传",
        type=["csv", "xlsx", "xls"],
        help="WPS表格 → 文件 → 导出 → CSV（或Excel）→ 上传到这里",
        key="file_uploader",
    )

    if uploaded_file is not None:
        try:
            raw_df = load_csv(uploaded_file)
            df = reshape_data(raw_df)

            st.session_state.data = df
            st.session_state.data_available_dates = sorted(df["date"].unique())

            st.success(f"✅ 加载成功！{len(raw_df)}条记录，{len(df)}条项目数据")
            st.caption(f"数据范围：{df['date'].min()} ~ {df['date'].max()}")
            st.caption(f"共 {df['plate'].nunique()} 个板块，{df['project'].nunique()} 个项目")

        except Exception as e:
            st.error(f"❌ 加载失败：{e}")
            st.info(
                "请确认CSV文件包含以下列：\n"
                "• 日期\n"
                "• 项目名称1~4\n"
                "• 游客量1~4\n"
                "• 收入1~4"
            )

    st.divider()

    # ---- 查询设置 ----
    st.header("🔍 查询设置")

    if st.session_state.data is not None:
        df = st.session_state.data
        min_date = df["date"].min()
        max_date = df["date"].max()

        report_type = st.selectbox(
            "报告类型",
            options=["日报", "周报", "月报", "年报"],
            index=0,
        )
        st.session_state.report_type = report_type

        # 日期选择
        if report_type == "日报":
            target_date = st.date_input(
                "选择日期",
                value=max_date,
                min_value=min_date,
                max_value=max_date,
            )
        elif report_type == "周报":
            target_date = st.date_input(
                "选择该周任意一天",
                value=max_date,
                min_value=min_date,
                max_value=max_date,
            )
            wd = target_date.weekday()
            week_start = target_date - timedelta(days=wd)
            week_end = week_start + timedelta(days=6)
            st.caption(f"📅 本周：{week_start} ~ {week_end}")
        elif report_type == "月报":
            target_date = st.date_input(
                "选择该月任意一天",
                value=max_date,
                min_value=min_date,
                max_value=max_date,
            )
        elif report_type == "年报":
            years = sorted(set(d.year for d in df["date"]), reverse=True)
            target_year = st.selectbox("选择年份", options=years, index=0)
            target_date = date(target_year, 1, 1)

        st.session_state.target_date = target_date

        # 板块选择
        st.subheader("📌 板块筛选")
        all_plates = list(HIERARCHY.keys())
        plate_display = [HIERARCHY[p]["display"] for p in all_plates]

        select_all_plates = st.checkbox("全选板块", value=True)
        if select_all_plates:
            selected_plates = all_plates
        else:
            selected_plates = []
            for i, plate_key in enumerate(all_plates):
                if st.checkbox(plate_display[i], value=True, key=f"plate_{plate_key}"):
                    selected_plates.append(plate_key)

        # 项目精细选择
        st.subheader("📌 项目筛选")
        available_projects = []
        for pk in selected_plates:
            for proj_key, proj_info in HIERARCHY[pk]["projects"].items():
                available_projects.append((pk, proj_info["display"]))

        expand_projects = st.checkbox("展开逐个选择（默认全选）", value=False)
        if expand_projects:
            selected_projects = []
            for pk, proj_display in available_projects:
                if st.checkbox(proj_display, value=True, key=f"proj_{proj_display}"):
                    selected_projects.append(proj_display)
        else:
            selected_projects = [p[1] for p in available_projects]

        # 生成按钮
        st.divider()
        generate_btn = st.button(
            "🚀 生成报告",
            type="primary",
            use_container_width=True,
        )

    else:
        st.info("👆 请先上传WPS导出的CSV/Excel文件")
        report_type = "日报"
        target_date = date.today()
        selected_plates = []
        selected_projects = []
        generate_btn = False


# ============================================================
# 生成报告逻辑
# ============================================================

if generate_btn and st.session_state.data is not None:
    df = st.session_state.data

    if report_type == "日报":
        current_df = filter_by_date(df, target_date, target_date)
        prev_date = target_date - timedelta(days=1)
        prev_df = filter_by_date(df, prev_date, prev_date)

    elif report_type == "周报":
        wd = target_date.weekday()
        week_start = target_date - timedelta(days=wd)
        week_end = week_start + timedelta(days=6)
        current_df = filter_by_date(df, week_start, week_end)
        prev_start = week_start - timedelta(days=7)
        prev_end = week_end - timedelta(days=7)
        prev_df = filter_by_date(df, prev_start, prev_end)

    elif report_type == "月报":
        month_start = target_date.replace(day=1)
        if target_date.month == 12:
            month_end = date(target_date.year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(target_date.year, target_date.month + 1, 1) - timedelta(days=1)
        current_df = filter_by_date(df, month_start, month_end)
        prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
        prev_month_end = month_start - timedelta(days=1)
        prev_df = filter_by_date(df, prev_month_start, prev_month_end)

    elif report_type == "年报":
        current_df = df[df["date"].apply(lambda x: x.year) == target_year]
        prev_df = df[df["date"].apply(lambda x: x.year) == target_year - 1]

    # 筛选板块和项目
    current_df = filter_by_plates(current_df, selected_plates)
    current_df = filter_by_projects(current_df, selected_projects)

    if prev_df is not None and len(prev_df) > 0:
        prev_df = filter_by_plates(prev_df, selected_plates)
        prev_df = filter_by_projects(prev_df, selected_projects)

    # 生成报告
    type_map = {"日报": "daily", "周报": "weekly", "月报": "monthly", "年报": "yearly"}
    report_text = generate_report(
        current_df,
        type_map[report_type],
        target_date,
        prev_df if (prev_df is not None and len(prev_df) > 0) else None,
    )

    st.session_state.report = report_text
    st.session_state.current_df = current_df


# ============================================================
# 主区域：报告展示
# ============================================================

tab1, tab2 = st.tabs(["📝 格式化报告", "📋 数据明细"])

with tab1:
    if st.session_state.report:
        st.subheader("📝 生成的报告")

        # 将报告文本填入text_area（用户可直接Ctrl+A Ctrl+C复制）
        st.text_area(
            "报告内容",
            value=st.session_state.report,
            height=520,
            key="report_output",
            label_visibility="collapsed",
        )

        # 下载 + 复制按钮
        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "📥 下载为TXT文件",
                data=st.session_state.report,
                file_name=f"{st.session_state.report_type}_{st.session_state.target_date}.txt",
                mime="text/plain",
                use_container_width=True,
            )
        with c2:
            # 使用JS实现前端复制
            escaped = st.session_state.report.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
            copy_js = f"""
            <button onclick="
                navigator.clipboard.writeText(`{escaped}`).then(function() {{
                    this.innerText = '✅ 已复制！';
                    setTimeout(function() {{ this.innerText = '📋 点击复制到剪贴板'; }}.bind(this), 2000);
                }}.bind(this)).catch(function() {{
                    this.innerText = '❌ 复制失败，请手动选中上方文本';
                }}.bind(this));
            " style="
                width:100%;padding:8px 16px;background:#165DFF;color:white;
                border:none;border-radius:4px;cursor:pointer;font-size:14px;
            ">📋 点击复制到剪贴板</button>
            """
            st.components.v1.html(copy_js, height=45)

        st.caption("💡 也可直接选中上方文本框内的文字 → Ctrl+C（Mac: ⌘+C）复制")

    else:
        st.info("👈 请在左侧上传数据文件，选择日期和板块，然后点击「生成报告」")
        st.markdown("""
        ### 快速上手指南

        1. **导出数据**：打开WPS在线表格 → 文件 → 导出 → 下载为 **CSV** 格式
        2. **上传**：在左侧「数据上传」区域上传CSV文件
        3. **设置**：选择报告类型（日报/周报/月报/年报）、日期、板块
        4. **生成**：点击「生成报告」按钮
        5. **复制**：复制生成的文字报告

        ---
        📱 **手机端同样可用**：浏览器打开网址 → 点左上角 `>` 展开菜单 → 上传文件 → 生成报告
        """)

with tab2:
    current_df = st.session_state.current_df if st.session_state.current_df is not None else pd.DataFrame()

    if len(current_df) > 0:
        st.subheader("📋 当前查询数据明细")
        display_df = current_df.copy()
        display_df["游客量(万)"] = (display_df["visitors"] / 10000).round(4)
        display_df["收入(万)"] = (display_df["revenue"] / 10000).round(4)
        st.dataframe(
            display_df[["date", "plate", "project", "sub_project", "游客量(万)", "收入(万)"]],
            use_container_width=True,
            hide_index=True,
        )
        st.caption(f"共 {len(current_df)} 条项目记录")

        # 汇总统计
        total_v = current_df["visitors"].sum() / 10000
        total_r = current_df["revenue"].sum() / 10000
        st.metric("游客总量（万人次）", f"{total_v:.4f}")
        st.metric("收入合计（万元）", f"{total_r:.4f}")
    elif st.session_state.data is not None:
        st.info("请点击「生成报告」查看数据明细")
    else:
        st.info("请先上传数据文件")


# ============================================================
# 底部
# ============================================================

st.divider()
st.caption(
    "💡 使用说明："
    "① WPS在线表格 → 文件 → 导出 → CSV → "
    "② 上传到本页 → "
    "③ 选择报告类型/日期/板块 → "
    "④ 生成报告 → "
    "⑤ 一键复制使用  |  "
    "🔧 如需调整项目层级配置，请编辑 config.py"
)
