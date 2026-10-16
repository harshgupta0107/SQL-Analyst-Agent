"""Shared, theme-aware visual styling for the Streamlit interface."""

from __future__ import annotations

import streamlit as st


def apply_styles(compact: bool = False, theme: str = "Dark") -> None:
    """Apply layout, typography, and component styles using Streamlit theme vars."""
    hero_padding = "0.75rem 1rem" if compact else "1rem 1.2rem"
    title_size = "1.4rem" if compact else "1.8rem"
    palette = (
        "--background-color:#F6F8FB; --secondary-background-color:#FFFFFF; --text-color:#172033; --primary-color:#126782;"
        if theme == "Light"
        else "--background-color:#0B1220; --secondary-background-color:#121D2E; --text-color:#F2F6FC; --primary-color:#58C4DD;"
    )
    color_scheme = "light" if theme == "Light" else "dark"
    st.markdown(
        f"""
        <style>
          :root {{ color-scheme: {color_scheme}; {palette} }}
          [data-testid="stAppViewContainer"] {{ background-color:var(--background-color); color:var(--text-color); }}
          [data-testid="stSidebar"] {{ background-color:var(--secondary-background-color); color:var(--text-color); }}
          .block-container {{ max-width: 1040px; padding-top: 1.3rem; padding-bottom: 2rem; }}
          [data-testid="stSidebar"] {{ border-right: 1px solid var(--secondary-background-color); }}
          [data-testid="stSidebar"] label, [data-testid="stSidebar"] .stCaption {{ font-size: .95rem; }}
          .hero {{ padding: {hero_padding}; border: 1px solid rgba(148,163,184,.28); border-radius: 16px;
            background: linear-gradient(125deg, var(--secondary-background-color), var(--background-color)); margin-bottom: .65rem; }}
          .hero-kicker {{ font-size: .76rem; font-weight: 750; letter-spacing: .11em; color: var(--primary-color); text-transform: uppercase; }}
          .hero-title {{ font-size: {title_size}; line-height: 1.2; font-weight: 750; color: var(--text-color); margin: .2rem 0; }}
          .hero-copy {{ font-size: .98rem; color: var(--text-color); opacity: .86; margin: 0; }}
          .source-pill {{ display:inline-flex; align-items:center; gap:.45rem; border:1px solid rgba(88,196,221,.5);
            background:var(--secondary-background-color); border-radius:99px; color:var(--text-color); padding:.35rem .75rem; font-size:.86rem; font-weight:650; }}
          .source-dot {{ width:.55rem; height:.55rem; display:inline-block; border-radius:50%; background:#27c281; }}
          .answer-headline {{ font-size:1.25rem; font-weight:700; line-height:1.35; margin:.25rem 0 .6rem; }}
          .assumptions-box {{ border:1px solid rgba(148,163,184,.3); background:var(--secondary-background-color); border-radius:12px; padding:.7rem .9rem; margin:.4rem 0 .8rem; }}
          .answer-footer {{ color:var(--text-color); opacity:.82; font-size:.84rem; border-top:1px solid rgba(148,163,184,.2); padding-top:.5rem; margin-top:.65rem; }}
          div[data-testid="stChatMessage"] {{ border:1px solid rgba(148,163,184,.2); border-radius:14px; padding:.8rem 1rem; margin-bottom:.8rem; }}
          div[data-testid="stChatInput"] {{ border-color:rgba(148,163,184,.45); }}
          div[data-testid="stDataFrame"] {{ border:1px solid rgba(148,163,184,.28); border-radius:10px; }}
          h1 {{ font-size:2rem; }} h2, h3 {{ font-size:1.25rem; }}
          @media (max-width: 800px) {{ .block-container {{ padding:1rem .65rem 1.5rem; }} }}
        </style>
        """,
        unsafe_allow_html=True,
    )
