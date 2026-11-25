#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نسخة احتياطية يومية — يُجدوَل عبر Scheduled Tasks في PythonAnywhere.

الأمر المقترح في Cron:
    /home/khateebs/.virtualenvs/mosqiyUN/bin/python /home/khateebs/mosqiyUN/backup_daily.py

ينشئ نسخة في instance/ ويحتفظ بآخر 5 نسخ فقط، ثم يطبع رابط التنزيل.
"""

import os
import sys
import glob
import shutil
import sqlite3
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

INSTANCE_DIR = os.path.join(PROJECT_DIR, 'instance')
DB_PATH = os.path.join(INSTANCE_DIR, 'khutba_distribution.db')
PREFIX = 'khutba_backup_'
KEEP = 5


def create_backup():
    """نسخة متسقة عبر sqlite backup API"""
    if not os.path.exists(DB_PATH):
        print('[backup] لا توجد قاعدة بيانات')
        return None

    os.makedirs(INSTANCE_DIR, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest = os.path.join(INSTANCE_DIR, '%s%s.db' % (PREFIX, stamp))

    src = sqlite3.connect(DB_PATH)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dest


def prune(keep=KEEP):
    """حذف النسخ الأقدم، مع الإبقاء على آخر `keep` نسخ"""
    files = sorted(glob.glob(os.path.join(INSTANCE_DIR, PREFIX + '*.db')))
    removed = 0
    for f in files[:-keep] if len(files) > keep else []:
        try:
            os.remove(f)
            removed += 1
        except OSError:
            pass
    return removed


def main():
    dest = create_backup()
    if not dest:
        return 1

    removed = prune()
    size_kb = os.path.getsize(dest) // 1024
    print('[backup] تم إنشاء نسخة: %s (%d KB)' % (os.path.basename(dest), size_kb))
    if removed:
        print('[backup] حُذفت %d نسخة قديمة' % removed)

    total = len(glob.glob(os.path.join(INSTANCE_DIR, PREFIX + '*.db')))
    print('[backup] عدد النسخ المحفوظة: %d' % total)
    return 0


if __name__ == '__main__':
    sys.exit(main())
