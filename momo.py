import re
import time

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from curl_cffi import requests

API_URL = "https://apisearch.momoshop.com.tw/momoSearchCloud/moec/textSearch"
HOME_URL = "https://www.momoshop.com.tw/"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": "https://www.momoshop.com.tw/",
}


def build_payload(keyword: str, page: int) -> dict:
    return {
        "host": "momoshop",
        "flag": "searchEngine",
        "data": {
            "searchValue": keyword,
            "searchType": "1",
            "cateLevel": "-1",
            "curPage": str(page),
            "priceS": "0",
            "priceE": "9999999",
            "showType": "chessboardType",
            "isFuzzy": "0",
            "rtnCateDatainfo": {
                "cateCode": "",
                "cateLv": "-1",
                "keyword": keyword,
                "curPage": str(page),
                "historyDoPush": "false",
                "timestamp": int(time.time() * 1000),
            },
            "flag": 2018,
            "serviceCode": "MT01",
            "addressSearchData": {},
        },
    }


@st.cache_data(show_spinner=False, ttl=600)
def scrape(keyword: str, pages: int, delay: float = 1.0) -> pd.DataFrame:
    session = requests.Session(impersonate="chrome")
    session.get(HOME_URL, headers=HEADERS)  # 先取得 cookie
    rows = []
    for page in range(1, pages + 1):
        resp = session.post(API_URL, headers=HEADERS, json=build_payload(keyword, page))
        if resp.status_code != 200:
            raise RuntimeError(f"第 {page} 頁請求失敗，HTTP {resp.status_code}：{resp.text[:200]}")
        goods = resp.json().get("rtnSearchData", {}).get("goodsInfoList", [])
        if not goods:
            break
        for p in goods:
            rows.append(
                {
                    "頁數": page,
                    "品名": p.get("goodsName", ""),
                    "價格": p.get("goodsPrice", ""),
                }
            )
        time.sleep(delay)

    df = pd.DataFrame(rows, columns=["頁數", "品名", "價格"])
    if df.empty:
        return df
    df["價格"] = df["價格"].astype(str).str.replace(r"[^\d]", "", regex=True)
    df = df[df["價格"] != ""].copy()
    df["價格"] = df["價格"].astype(int)
    return df.reset_index(drop=True)


def extract_brand(name: str) -> str:
    """取品名開頭【】內文字當品牌；沒有就歸為「其他」（簡易規則，非精準）。"""
    m = re.search(r"【(.+?)】", name)
    return m.group(1).strip() if m else "其他"


def add_price_bins(df: pd.DataFrame, n_bins: int = 5) -> pd.DataFrame:
    df = df.copy()
    try:
        df["價格區間"] = pd.qcut(df["價格"], q=n_bins, duplicates="drop").astype(str)
    except ValueError:
        df["價格區間"] = "全部"
    return df


# ---------------- UI ----------------
st.set_page_config(page_title="MOMO 商品價格分析", layout="wide")
st.title("MOMO 商品價格分析")

with st.sidebar:
    keyword = st.text_input("產品名稱", value="行動電源")
    pages = st.number_input("爬取頁數", min_value=1, max_value=20, value=1, step=1)
    top_n = st.slider("圓餅圖/旭日圖顯示前幾大品牌", 3, 15, 8)
    run = st.button("開始爬取", type="primary")

if run:
    if not keyword.strip():
        st.warning("請輸入產品名稱")
        st.stop()
    try:
        with st.spinner("爬取中..."):
            st.session_state["df"] = scrape(keyword.strip(), int(pages))
            st.session_state["kw"] = keyword.strip()
    except Exception as e:
        st.error(f"爬取失敗：{e}")
        st.stop()

df = st.session_state.get("df")
if df is None:
    st.info("請在左側輸入產品名稱與頁數，按「開始爬取」。")
    st.stop()
if df.empty:
    st.warning("沒有取得資料（可能被擋或關鍵字無結果）。")
    st.stop()

kw = st.session_state["kw"]
mean_price = df["價格"].mean()

c1, c2, c3, c4 = st.columns(4)
c1.metric("商品數", len(df))
c2.metric("平均價格", f"{mean_price:,.0f}")
c3.metric("最高價格", f"{df['價格'].max():,}")
c4.metric("最低價格", f"{df['價格'].min():,}")

# 折線圖
st.subheader("價格折線圖")
fig_line = px.line(
    df, x=df.index, y="價格", hover_name="品名",
    labels={"x": "商品序號", "價格": "價格 (元)"},
    title=f"MOMO 電商網站上「{kw}」售價",
)
fig_line.add_hline(
    y=mean_price, line_dash="dash", line_color="red",
    annotation_text=f"平均 {mean_price:,.0f}",
)
st.plotly_chart(fig_line, use_container_width=True)

# 圓餅圖：價格區間
df = add_price_bins(df)
df["品牌"] = df["品名"].apply(extract_brand)

col_a, col_b = st.columns(2)
with col_a:
    st.subheader("價格區間圓餅圖")
    bin_count = df["價格區間"].value_counts().reset_index()
    bin_count.columns = ["價格區間", "數量"]
    st.plotly_chart(
        px.pie(bin_count, names="價格區間", values="數量"),
        use_container_width=True,
    )

# 旭日圖：價格區間 -> 品牌
with col_b:
    st.subheader("旭日圖（價格區間 → 品牌）")
    top_brands = df["品牌"].value_counts().head(top_n).index
    sun_df = df.copy()
    sun_df.loc[~sun_df["品牌"].isin(top_brands), "品牌"] = "其他"
    sun_df = sun_df.groupby(["價格區間", "品牌"]).size().reset_index(name="數量")
    st.plotly_chart(
        px.sunburst(sun_df, path=["價格區間", "品牌"], values="數量"),
        use_container_width=True,
    )

st.caption("品牌為取品名開頭【】內文字的簡易規則，沒有【】者歸為「其他」。")

with st.expander("原始資料"):
    st.dataframe(df[["頁數", "品名", "價格", "價格區間", "品牌"]], use_container_width=True)
    st.download_button(
        "下載 CSV",
        df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
        file_name=f"MOMO_{kw}_{time.strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
