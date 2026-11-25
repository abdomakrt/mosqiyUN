# ============================================================
#  دليل النشر على PythonAnywhere
#  نظام توزيع الخطباء
# ============================================================

## نظرة عامة

| البند | القيمة |
|---|---|
| المستودع | `https://github.com/abdomakrt/mosqiyUN.git` |
| الخادم | `https://khateebs.pythonanywhere.com` |
| مجلد التطبيق | `/home/khateebs/mosqiyUN` |
| البيئة الافتراضية | `/home/khateebs/.virtualenvs/mosqiyUN` |
| ملف WSGI | `/home/khateebs/mosqiyUN/wsgi.py` |
| قاعدة البيانات | `/home/khateebs/mosqiyUN/instance/khutba_distribution.db` |
| Python | 3.12 |

---

## الخطوة 1 — تفعيل Python 3.12

من لوحة PythonAnywhere:

1. تبويب **Files** → المجلد `/home/khateebs/` → اضغط **Python 3.12** (إنشاء virtualenv)
2. أو: تبويب **Consoles** → اختر Python 3.12

---

## الخطوة 2 — تشغيل سكربت النشر

افتح **Console** (Python 3.12) ونفّذ:

```bash
curl -fsSL https://raw.githubusercontent.com/abdomakrt/mosqiyUN/main/setup_paw.sh | bash
```

أو إذا كان الكود منزّلاً بالفعل:

```bash
cd ~/mosqiyUN && bash setup_paw.sh
```

### ماذا سيطبع؟

```
[1] مفسر Python: /home/khateebs/.local/bin/python3.12
[2] تنزيل الكود من GitHub...
[3] تجهيز البيئة الافتراضية...
[4] ...
============================================
  كلمة مرور المدير على الخادم (تظهر مرة واحدة):
      xK9mN2pQ7wZa
============================================
  احفظها الآن في مكان آمن.
[6] تجهيز قاعدة البيانات...
[7] فحص الجاهزية...
```

> ⚠️ **كلمة مرور المدير تُعرض مرة واحدة فقط** — احفظها فوراً.
> يمكنك تغييرها لاحقاً من: **الإعدادات ← كلمة مرور المدير**

---

## الخطوة 3 — ضبط الـ Web App

تبويب **Web** → اختر `khateebs.pythonanywhere.com`:

| الحقل | القيمة |
|---|---|
| Source code | `/home/khateebs/mosqiyUN` |
| Working directory | `/home/khateebs/mosqiyUN` |
| Virtualenv | `/home/khateebs/.virtualenvs/mosqiyUN` |
| WSGI configuration file | `/home/khateebs/mosqiyUN/wsgi.py` |

اضغط **Save** ثم **Reload** (الرفع العمودي Green ✓).

---

## الخطوة 4 — التحقق

```bash
/home/khateebs/.virtualenvs/mosqiyUN/bin/python /home/khateebs/mosqiyUN/check_paw.py
```

يجب أن تطبع:

```
 النتيجة: كل الفحوص ناجحة ✅
```

ثم افتح: **https://khateebs.pythonanywhere.com**

---

## الخطوة 5 — النسخ الاحتياطي اليومي

تبويب **Tasks** → Scheduled task:

| الحقل | القيمة |
|---|---|
| Frequency | Daily |
| Time | 03:00 (أي وقت) |
| Command | `/home/khateebs/.virtualenvs/mosqiyUN/bin/python /home/khateebs/mosqiyUN/backup_daily.py` |

> الخطة المجانية تسمح بمهمة **يومية واحدة** — وهذا يكفي.
> يحتفظ بآخر **5** نسخ، وكلها متاحة للتنزيل من:
> **الإعدادات ← النسخ الاحتياطي والاستعادة**

### استعادة النسخة (عند الحاجة)

1. من صفحة الإعدادات ← «النسخ الاحتياطي والاستعادة» ← نزّل نسخة إلى جهازك
2. ارفعها عبر نفس الصفحة ← «استعادة من ملف»
3. (اختياري) أو من الـ Console:

```bash
cd ~/mosqiyUN && cp instance/backup_XXXX.db instance/khutba_distribution.db
```

> يتم حفظ نسخة أمان من الوضع الحالي تلقائياً قبل أي استعادة.

---

## التحديثات (git pull)

```bash
cd ~/mosqiyUN && git pull origin main
```

ثم من تبويب **Web** → **Reload**.

> ⚠️ `git pull` **لا يمسّ** ملف `.env` ولا مجلد `instance/` (مستثنيان في `.gitignore`).

---

## الأمان

| الإجراء | كيف |
|---|---|
| HTTPS | فعّل **Force HTTPS** من تبويب Web |
| `SESSION_COOKIE_SECURE` | اضبط `SESSION_COOKIE_SECURE=1` في `.env` بعد تفعيل HTTPS |
| كلمة مرور المدير | غيّرها من الإعدادات (تُخزَّن مشفّرة في `app_setting`) |
| `SECRET_KEY` | يُولَّد تلقائياً عند أول نشر (32 بايت عشوائية) |
| حماية الوصول | فعّل **Password protection** لتقييد الوصول للإدارة |

---

## استكشاف الأخطاء

### `ModuleNotFoundError: No module named 'flask'`

الـ virtualenv غير صحيح. تأكد أن مسار Virtualenv في تبويب Web هو:
`/home/khateebs/.virtualenvs/mosqiyUN` — أو أعد التثبيت:

```bash
~/mosqiyUN/setup_paw.sh
```

### `unable to open database file`

مجلد `instance/` غير موجود أو غير قابل للكتابة:

```bash
mkdir -p ~/mosqiyUN/instance && chmod 700 ~/mosqiyUN/instance
```

### الصفحة تُعرض لكن البيانات فارغة

الترحيل لم يُنفَّذ:

```bash
~/.virtualenvs/mosqiyUN/bin/python -c "import sys; sys.path.insert(0,'/home/khateebs/mosqiyUN'); from app import app, db, ensure_schema; ensure_schema(); app.app_context().push(); db.create_all()"
```

### أخطاء في السجل

```bash
tail -50 ~/mosqiyUN/instance/*.log 2>/dev/null
```

أو من **Web** → تبويب **Error log**.

### التغييرات لا تظهر

- حدّث `TEMPLATES_AUTO_RELOAD` في `app.py` إلى `False` (أداء أفضل) — أو اضغط **Reload** من تبويب Web.
- `app.config['TEMPLATES_AUTO_RELOAD'] = True` حالياً (مفيد أثناء التطوير).

---

## حدود الخطة المجانية

| الحد | القيمة | هل يؤثر؟ |
|---|---|---|
| CPU يومي | 100 ثانية | ⚠️ التطبيق خفيف الاستخدام — راقب الاستهلاك |
| Web Apps | 1 | ✅ مستخدم واحد |
| Scheduled tasks | 1 يومية | ✅ للنسخ الاحتياطي |
| Storage | 512 MB | ✅ كافٍ |
| Domains مخصصة | غير متاحة | استخدم `khateebs.pythonanywhere.com` |

> إذا زاد الاستهلاك، استخدم **Render** أو **Railway** (Both have free tiers with more headroom).

---

## تذكير

- `instance/` و `.env` **غير مرفوعان** لـ GitHub (خصوصية + أسرار).
- قاعدة البيانات تُنشأ تلقائياً عند أول إقلاع عبر `ensure_schema()` و `db.create_all()`.
- كل التغييرات موثّقة في تاريخ Git.
