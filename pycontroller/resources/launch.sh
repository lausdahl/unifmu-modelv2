#!/usr/bin/env sh

python3 -m venv .venv
source .venv/bin/bash

pip install -r requirements.txt
python backend.py