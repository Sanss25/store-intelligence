import os
import time

import pandas as pd
import requests
import streamlit as st

API_URL = os.environ.get("STORE_INTEL_API_URL", "http://127.0.0.1:8000")
STORE_ID = os.environ.get("STORE_INTEL_STORE_ID", "STORE_1")
REFRESH_SECONDS = 5

st.set_page_config(page_title="Store Analytics Dashboard", layout="wide", page_icon="🏪")


def fetch(path: str) -> dict | None:
    try:
        resp = requests.get(f"{API_URL}{path}", timeout=3)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        st.error(f"Could not reach API at {API_URL}{path}: {exc}")
        return None


st.title("🏪 Store Analytics Dashboard")
st.caption(f"Store: {STORE_ID}  ·  API: {API_URL}  ·  auto-refreshing every {REFRESH_SECONDS}s")

health = fetch("/health")
metrics = fetch(f"/stores/{STORE_ID}/metrics")

if health:
    status_ok = health.get("status") == "ok" and health.get("db_connected")
    (st.success if status_ok else st.warning)(
        f"API {health.get('status', 'unknown')} · {health.get('total_events', 0)} total events ingested"
    )

if metrics:
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Unique Visitors", metrics["unique_visitors"])
    col2.metric("Occupancy", metrics["occupancy"])
    col3.metric("Entries", metrics["entries"])
    col4.metric("Exits", metrics["exits"])
    col5.metric("Conversion", f"{metrics['conversion_rate']}%")

    col6, col7 = st.columns(2)
    col6.metric("Avg Dwell Time", f"{metrics['avg_dwell_ms'] / 1000:.1f}s" if metrics["avg_dwell_ms"] else "—")
    col7.metric("Current Queue Depth", metrics["current_queue_depth"])

st.divider()

tab_funnel, tab_heatmap, tab_anomalies, tab_health = st.tabs(
    ["Conversion Funnel", "Zone Heatmap", "Anomalies", "System Health"]
)

with tab_funnel:
    funnel = fetch(f"/stores/{STORE_ID}/funnel")
    if funnel and funnel.get("stages"):
        df = pd.DataFrame(funnel["stages"])
        st.bar_chart(df.set_index("stage")["visitors"])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No funnel data yet — ingest some events first.")

with tab_heatmap:
    heatmap = fetch(f"/stores/{STORE_ID}/heatmap")
    if heatmap and heatmap.get("zones"):
        df = pd.DataFrame(heatmap["zones"])
        st.bar_chart(df.set_index("zone_id")["heat_score"])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No zone data yet — zone_id isn't populated by the entry-line pipeline alone.")

with tab_anomalies:
    anomalies = fetch(f"/stores/{STORE_ID}/anomalies")
    if anomalies and anomalies.get("anomalies"):
        for a in anomalies["anomalies"]:
            icon = {"low": "🟡", "medium": "🟠", "high": "🔴"}.get(a["severity"], "⚪")
            st.write(f"{icon} **{a['type']}** — {a['message']}")
    else:
        st.success("No anomalies detected.")

with tab_health:
    if health:
        st.json(health)

time.sleep(REFRESH_SECONDS)
st.rerun()
