#!/usr/bin/env bash
# Opens Streamlit Community Cloud deploy with accord-headhunter prefilled.
# Set GITHUB_REPO to your org/repo (default: meweir/accord-headhunter).

REPO="${GITHUB_REPO:-meweir/accord-headhunter}"
open "https://share.streamlit.io/deploy?repository=${REPO}&branch=main&mainModule=dashboard%2Fapp.py"
