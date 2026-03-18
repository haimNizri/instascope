#!/usr/bin/env bash
set -e

pip install --upgrade pip
pip install -r requirements.txt

# Initialize database tables
python -c "from app import app, db; app.app_context().__enter__(); db.create_all(); print('DB tables created')"
