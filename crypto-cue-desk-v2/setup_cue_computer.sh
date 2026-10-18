#!/usr/bin/env bash
set -e
echo "=== Cài đặt Crypto Cue Desk trên Cloud Computer của Cue by Manus ==="
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -c "from db_manager import init_db; init_db()"
echo "=== Khởi tạo thành công SQLite Cognitive Database tại data/db/learning.db ==="
python3 cue_desk_cli.py portfolio
