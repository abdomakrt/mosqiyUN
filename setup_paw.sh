#!/usr/bin/env bash
# ============================================================
#  سكربت نشر نظام توزيع الخطباء على PythonAnywhere
#
#  الاستخدام (داخل PythonAnywhere Console):
#      bash setup_paw.sh
#
#  ما يفعله:
#    1) ينسخ الكود من GitHub
#    2) ينشئ بيئة افتراضية ويثبّت المتطلبات
#    3) ينشئ .env مع مفتاح سري وكلمة مرور مدير (وتطبعها مرة واحدة)
#    4) يهيّئ قاعدة البيانات والجداول الأساسية (ترحيل idempotent)
#    5) يضبط ملف WSGI الخاص بـ PythonAnywhere تلقائياً
# ============================================================
set -e

APP_DIR="$HOME/mosqiyUN"
VENV="$HOME/.virtualenvs/mosqiyUN"
REPO="https://github.com/abdomakrt/mosqiyUN.git"
PAW_WSGI="/var/www/${USER}_pythonanywhere_com_wsgi.py"

echo "============================================"
echo "  نشر نظام توزيع الخطباء - PythonAnywhere"
echo "============================================"
echo

# ---------- 1) مفسر Python ----------
PY_BIN="$HOME/.local/bin/python3.12"
if [ ! -x "$PY_BIN" ]; then
    PY_BIN=$(command -v python3.12 2>/dev/null || command -v python3 || true)
fi
if [ -z "$PY_BIN" ]; then
    echo "[X] لم يُعثر على Python. تأكد أن Python 3.12 مفعّل في Files > Python."
    exit 1
fi
echo "[1] مفسر Python: $PY_BIN"
"$PY_BIN" --version

# ---------- 2) الكود ----------
mkdir -p "$APP_DIR"
cd "$APP_DIR"
if [ -d .git ]; then
    echo "[2] سحب آخر تحديثات من GitHub..."
    git pull --ff-only origin main 2>/dev/null || git pull origin main
else
    echo "[2] تنزيل الكود من GitHub..."
    git clone "$REPO" .
fi
echo "    المسار: $APP_DIR"

# ---------- 3) البيئة الافتراضية ----------
echo "[3] تجهيز البيئة الافتراضية..."
if [ ! -d "$VENV" ]; then
    "$PY_BIN" -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r requirements.txt
echo "    تم تثبيت المتطلبات"

# ---------- 4) متغيرات البيئة ----------
ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    "$VENV/bin/python" - <<'PYEOF'
import os
import secrets

secret = secrets.token_hex(32)
admin = secrets.token_urlsafe(12)
with open('.env', 'w', encoding='utf-8') as f:
    f.write('# متغيرات بيئة الإنتاج - لا تُشارك هذا الملف\n')
    f.write('SECRET_KEY=%s\n' % secret)
    f.write('ADMIN_PASSWORD=%s\n' % admin)
    f.write('SESSION_COOKIE_SECURE=0\n')
os.chmod('.env', 0o600)
print('============================================')
print('  كلمة مرور المدير على الخادم (تظهر مرة واحدة):')
print('      %s' % admin)
print('============================================')
print('  احفظها الآن في مكان آمن.')
print('  يمكنك تغييرها لاحقاً من: صفحة الإعدادات > كلمة مرور المدير')
PYEOF
else
    echo "[4] ملف .env موجود مسبقاً (لم يُمس)"
fi

# ---------- 5) مجلد instance ----------
mkdir -p "$APP_DIR/instance"
echo "[5] مجلد instance جاهز"

# ---------- 6) قاعدة البيانات ----------
echo "[6] تجهيز قاعدة البيانات..."
"$VENV/bin/python" - <<'PYEOF'
import os
import sys

sys.path.insert(0, os.getcwd())
from app import app, db, ensure_schema

ensure_schema()
with app.app_context():
    db.create_all()
print('    اكتملت تهيئة قاعدة البيانات والجداول')
PYEOF

# ---------- 7) ضبط ملف WSGI تلقائياً ----------
echo "[7] ضبط ملف WSGI..."
if [ -f "$PAW_WSGI" ] || [ -w "/var/www" ]; then
    cat <<WSGIEOF > "$PAW_WSGI"
import os
import sys

project_home = '$APP_DIR'
if project_home not in sys.path:
    sys.path.insert(0, project_home)
os.chdir(project_home)

import wsgi
application = getattr(wsgi, 'application', getattr(wsgi, 'app', None))
WSGIEOF
    echo "    تم تحديث ملف WSGI تلقائياً: $PAW_WSGI"
else
    echo "    [!] لم يُعثر على $PAW_WSGI بعد (تأكد من إنشاء Web App في تبويب Web أولاً)"
fi

# ---------- 8) الفحص ----------
echo "[8] فحص الجاهزية..."
"$VENV/bin/python" check_paw.py || true

echo
echo "============================================"
echo "  اكتمل الإعداد!"
echo "============================================"
echo
echo "  الخطوة الأخيرة في لوحة PythonAnywhere:"
echo "    1) تبويب Web"
echo "    2) اختر:  ${USER}.pythonanywhere.com"
echo "    3) Source code:        $APP_DIR"
echo "    4) Working directory:  $APP_DIR"
echo "    5) Virtualenv:         $VENV"
echo "    6) WSGI configuration file: (تم ضبطه تلقائياً في $PAW_WSGI)"
echo "    7) اضغط:  Reload"
echo
echo "  ثم افتح:  https://${USER}.pythonanywhere.com"
echo
