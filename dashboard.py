import streamlit as st
import requests

st.set_page_config(
    page_title="Store Analytics Dashboard",
    layout="wide"
)

st.title("🏪 Store Analytics Dashboard")

health = requests.get(
    "http://127.0.0.1:8000/health"
).json()

metrics = requests.get(
    "http://127.0.0.1:8000/stores/STORE_1/metrics"
).json()

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        "Unique Visitors",
        metrics["unique_visitors"]
    )

with col2:
    st.metric(
        "Occupancy",
        metrics["occupancy"]
    )

with col3:
    st.metric(
        "Entries",
        metrics["entries"]
    )

with col4:
    st.metric(
        "Exits",
        metrics["exits"]
    )

st.divider()

st.subheader("System Health")

st.json(health)

st.success("Pipeline Connected Successfully")