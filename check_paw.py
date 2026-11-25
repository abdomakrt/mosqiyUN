#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
فحص سريع للتطبيق على الخادم — شغّله داخل PythonAnywhere Console:

    python3 check_paw.py

يتحقق من: المتغيرات، قاعدة البيانات، الجداول، الاستيرادات، والمسارات.
"""

import os
import sys
from importlib.metadata import version

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

ok = True


def line(char='-'):
    print(char * 60)


def check(label, condition, detail=''):
    global ok
    if not condition:
        ok = False
    print(('  [OK]  ' if condition else '  [!!]  ') + label + (('  -> ' + str(detail)) if detail else ''))


print()
print('=' * 60)
print(' فحص جاهزية نظام توزيع الخطباء')
print('=' * 60)
print()

# ---------- 1) متغيرات البيئة ----------
print('1) متغيرات البيئة')
env_file = os.path.join(PROJECT_DIR, '.env')
if os.path.exists(env_file):
    with open(env_file, encoding='utf-8') as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if raw_line and not raw_line.startswith('#') and '=' in raw_line:
                k, v = raw_line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

check('SECRET_KEY مضبوط', bool(os.environ.get('SECRET_KEY')),
      'مضبوط' if os.environ.get('SECRET_KEY') else 'مفقود (سيُستخدم مفتاح تطوير)')
check('ADMIN_PASSWORD مضبوط', bool(os.environ.get('ADMIN_PASSWORD')),
      'مضبوط' if os.environ.get('ADMIN_PASSWORD') else 'مفقود')

# ---------- 2) الاستيرادات ----------
print()
print('2) المكتبات')
try:
    import flask
    check('Flask', True, version('flask'))
except Exception as e:
    check('Flask', False, e)
try:
    import flask_sqlalchemy
    check('Flask-SQLAlchemy', True, version('flask-sqlalchemy'))
except Exception as e:
    check('Flask-SQLAlchemy', False, e)
try:
    import werkzeug
    check('Werkzeug', True, version('werkzeug'))
except Exception as e:
    check('Werkzeug', False, e)

# ---------- 3) التطبيق ----------
print()
print('3) التطبيق وقاعدة البيانات')
try:
    from app import app, db, ensure_schema
    check('استيراد التطبيق', True)
    with app.app_context():
        db.create_all()
        ensure_schema()
        check('تهيئة الجداول (ensure_schema)', True)

        from models import Mosque, Khateb, Assignment, WeeklySchedule, AppSetting
        check('جدول المساجد', Mosque.query.count() is not None, '%d مسجد' % Mosque.query.count())
        check('جدول الخطباء', Khateb.query.count() is not None, '%d خطيب' % Khateb.count() if hasattr(Khateb, 'count') else '%d خطيب' % Khateb.query.count())
        check('جدول التعيينات', Assignment.query.count() is not None, '%d تعيين' % Assignment.query.count())

        db_path = os.path.join(app.instance_path, 'khutba_distribution.db')
        check('ملف قاعدة البيانات موجود', os.path.exists(db_path), db_path)
        check('مجلد instance قابل للكتابة', os.access(app.instance_path, os.W_OK),
              app.instance_path)

        # ---------- 4) المسارات ----------
        print()
        print('4) المسارات الأساسية')
        rules = {r.rule for r in app.url_map.iter_rules()}
        for r in ['/login', '/logout', '/register', '/my', '/my/profile',
                  '/settings', '/khutbas', '/mosques', '/distribution']:
            check('المسار %s' % r, r in rules)

        # ---------- 5) صفحات ----------
        print()
        print('5) استجابة الصفحات')
        client = app.test_client()
        for path, expect in [('/login', 200), ('/register', 200)]:
            resp = client.get(path)
            check('%s -> %s' % (path, expect), resp.status_code == expect, resp.status_code)
        resp = client.get('/my')
        check('/my محمي (302 للدخول)', resp.status_code == 302, resp.status_code)
        resp = client.get('/settings')
        check('/settings محمي (302 للدخول)', resp.status_code == 302, resp.status_code)
except Exception as e:
    check('تشغيل التطبيق', False, '%s: %s' % (type(e).__name__, e))
    import traceback
    traceback.print_exc()

print()
line('=')
print(' النتيجة: ' + ('كل الفحوص ناجحة ✅' if ok else 'توجد مشاكل ❌'))
line('=')
print()
sys.exit(0 if ok else 1)
