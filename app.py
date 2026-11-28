# -*- coding: utf-8 -*-
"""
نظام توزيع خطباء الجمعة على المساجد (Clean Mosqiy)
تطبيق خفيف، عالي الكفاءة، متجاوب 100% مع الجوال والشاشات.
"""
import os
import re
import json
import shutil
from datetime import datetime, date, timedelta
from functools import wraps
from urllib.parse import quote

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, jsonify, send_file, g
)

from models import (
    db, Mosque, Khateb, Assignment, WeeklySchedule, AppSetting,
    get_friday_week_index
)
from engine import DistributionEngine

app = Flask(__name__)

# الإعدادات
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'mosqiy-secret-key-2026-safe')
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
os.makedirs(INSTANCE_DIR, exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(INSTANCE_DIR, 'khutba_distribution.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'

db.init_app(app)

engine = DistributionEngine()


# ====================================================
# دوال إدارة الجلسة والمصادقة (Authentication Helpers)
# ====================================================

def is_admin():
    return session.get('role') == 'admin'

def current_khateb():
    if session.get('role') == 'khateb' and session.get('khateb_id'):
        return db.session.get(Khateb, session['khateb_id'])
    return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash('يرجى تسجيل الدخول أولاً للوصول إلى هذه الصفحة', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('هذه الصفحة مخصصة لمدير النظام فقط', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def load_logged_in_user():
    g.is_admin = is_admin()
    g.current_khateb = current_khateb()


# ====================================================
# دوال التحقق وتجهيز بيانات الجمعات (Validation & Helpers)
# ====================================================

ARABIC_TO_ASCII_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def normalize_phone(phone):
    """توحيد صيغة رقم الجوال وتحويل الأرقام العربية إلى إنجليزية"""
    if not phone:
        return ''
    return phone.translate(ARABIC_TO_ASCII_DIGITS).strip().replace(' ', '').replace('-', '')


def validate_khateb_inputs(name, phone):
    """التحقق من صحة الاسم (دون أرقام) ورقم الجوال (أرقام فقط)"""
    name_clean = ' '.join((name or '').split())
    phone_clean = normalize_phone(phone)

    if not name_clean or len(name_clean) < 2:
        return False, 'اسم الخطيب مطلوب ويجب أن لا يقل عن حرفين', name_clean, phone_clean

    if re.search(r'[0-9٠-٩۰-۹]', name_clean):
        return False, 'لا يمكن إدخال أرقام في حقل اسم الخطيب', name_clean, phone_clean

    if not re.search(r'[a-zA-Z\u0621-\u064A]', name_clean):
        return False, 'اسم الخطيب يجب أن يحتوي على حروف صحيحة', name_clean, phone_clean

    if not phone_clean:
        return False, 'رقم الجوال مطلوب', name_clean, phone_clean

    if not re.match(r'^\+?[0-9]{8,15}$', phone_clean):
        return False, 'رقم الجوال غير صحيح: يجب إدخال أرقام فقط (من 8 إلى 15 رقماً) دون حروف', name_clean, phone_clean

    return True, '', name_clean, phone_clean


def parse_unavailable_dates_from_form(form):
    """استخراج تواريخ عدم الإتاحة من مربعات الاختيار أو القائمة النصية"""
    raw_list = form.getlist('unavailable_dates')
    dates = []
    for item in raw_list:
        for part in item.split(','):
            d_str = part.strip()
            if d_str:
                try:
                    datetime.strptime(d_str, '%Y-%m-%d')
                    dates.append(d_str)
                except ValueError:
                    pass
    return sorted(list(set(dates)))


def get_friday_selection_context(num_weeks=12, extended_weeks=24):
    """تجهيز قائمة الجمعات القادمة وقيم بداية التناوب للواجهات"""
    next_friday = engine.get_current_friday()
    after_next_friday = next_friday + timedelta(days=7)
    next_idx = get_friday_week_index(next_friday)

    offset_next = next_idx % 2
    offset_after_next = (next_idx + 1) % 2

    upcoming_fridays = []
    for i in range(num_weeks):
        d = next_friday + timedelta(days=7 * i)
        tag = 'القادمة' if i == 0 else ('بعد القادمة' if i == 1 else f'بعد {i + 1} أسابيع')
        suffix = f' ({tag})' if i < 2 else ''
        upcoming_fridays.append({
            'date_str': d.strftime('%Y-%m-%d'),
            'label': f"الجمعة {d.strftime('%Y-%m-%d')}{suffix}",
            'tag': tag,
        })

    extended_fridays = []
    for i in range(num_weeks, extended_weeks):
        d = next_friday + timedelta(days=7 * i)
        extended_fridays.append({
            'date_str': d.strftime('%Y-%m-%d'),
            'label': f"الجمعة {d.strftime('%Y-%m-%d')}",
        })

    return {
        'next_friday': next_friday,
        'after_next_friday': after_next_friday,
        'offset_next': offset_next,
        'offset_after_next': offset_after_next,
        'upcoming_fridays': upcoming_fridays,
        'extended_fridays': extended_fridays,
    }


# ====================================================
# مسارات تسجيل الدخول والخروج والتسجيل
# ====================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_type = request.form.get('login_type', 'admin')

        if login_type == 'admin':
            password = request.form.get('password', '').strip()
            admin_hash = AppSetting.get('admin_password_hash')
            from werkzeug.security import check_password_hash, generate_password_hash

            # كلمة مرور المدير الافتراضية أو من متغير البيئة عند أول تشغيل
            if not admin_hash:
                default_pw = os.environ.get('ADMIN_PASSWORD', 'admin123')
                admin_hash = generate_password_hash(default_pw)
                AppSetting.set('admin_password_hash', admin_hash)

            if check_password_hash(admin_hash, password):
                session.clear()
                session['user_id'] = 'admin'
                session['role'] = 'admin'
                session['name'] = 'مدير النظام'
                flash('تم تسجيل دخول المدير بنجاح', 'success')
                return redirect(url_for('distribution'))
            else:
                flash('كلمة مرور المدير غير صحيحة', 'danger')

        elif login_type == 'khateb':
            phone = normalize_phone(request.form.get('phone', ''))
            password = request.form.get('password', '').strip()

            khateb = Khateb.query.filter_by(phone=phone).first()
            if khateb and khateb.check_password(password):
                if khateb.is_active != 1:
                    flash('حسابك قيد المراجعة وبانتظار موافقة الإدارة قبل التفعيل.', 'info')
                    return render_template('login.html')

                session.clear()
                session['user_id'] = khateb.id
                session['role'] = 'khateb'
                session['khateb_id'] = khateb.id
                session['name'] = khateb.name
                flash(f'مرحباً بك يا شيخ {khateb.name}', 'success')
                return redirect(url_for('my_portal'))
            else:
                flash('رقم الهاتف أو كلمة المرور غير صحيحة', 'danger')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """تسجيل خطيب جديد لنفسه (يبقى معلقاً حتى يفعله المدير)"""
    friday_ctx = get_friday_selection_context()
    if request.method == 'POST':
        raw_name = request.form.get('name', '')
        raw_phone = request.form.get('phone', '')
        password = request.form.get('password', '').strip()
        availability_mode = request.form.get('availability_mode', 'always')
        if availability_mode not in ('always', 'alternate'):
            availability_mode = 'always'
        alternate_offset_raw = request.form.get('alternate_offset')
        alternate_offset = int(alternate_offset_raw) if alternate_offset_raw in ('0', '1') else friday_ctx['offset_next']
        forbidden = [int(x) for x in request.form.getlist('forbidden_mosques') if x.isdigit()]
        initial_visited = [int(x) for x in request.form.getlist('initial_visited_mosques') if x.isdigit()]
        unavailable_dates = parse_unavailable_dates_from_form(request.form)

        if not password:
            flash('يرجى إدخال كلمة المرور', 'danger')
            return redirect(url_for('register'))

        valid, err_msg, name, phone = validate_khateb_inputs(raw_name, raw_phone)
        if not valid:
            flash(err_msg, 'danger')
            return redirect(url_for('register'))

        if Khateb.query.filter_by(phone=phone).first():
            flash('رقم الهاتف هذا مسجل لدينا بالفعل، يرجى تسجيل الدخول', 'warning')
            return redirect(url_for('login'))

        new_khateb = Khateb(
            name=name,
            phone=phone,
            is_active=0,  # بانتظار موافقة المدير صراحةً
            availability_mode=availability_mode,
            alternate_offset=alternate_offset,
            forbidden_mosques=json.dumps(sorted(list(set(forbidden)))),
            initial_visited_mosques=json.dumps(sorted(list(set(initial_visited)))),
            unavailable_dates=json.dumps(unavailable_dates),
            current_cycle=1
        )
        new_khateb.set_password(password)
        db.session.add(new_khateb)
        db.session.commit()

        flash('تم تسجيلك بنجاح! حسابك بانتظار تفعيل الإدارة ولن يتم إدراجك في التوزيع حتى تتم الموافقة.', 'success')
        return redirect(url_for('login'))

    mosques = Mosque.query.all()
    return render_template('register.html', mosques=mosques, **friday_ctx)


@app.route('/logout')
def logout():
    session.clear()
    flash('تم تسجيل الخروج بنجاح', 'info')
    return redirect(url_for('login'))


# ====================================================
# إدارة المساجد (Mosque Management)
# ====================================================

@app.route('/mosques')
@admin_required
def mosques():
    all_mosques = Mosque.query.order_by(Mosque.id.desc()).all()
    return render_template('mosques.html', mosques=all_mosques)

@app.route('/mosque/add', methods=['POST'])
@admin_required
def add_mosque():
    name = request.form.get('name', '').strip()
    address = request.form.get('address', '').strip()
    capacity = int(request.form.get('capacity') or 0)
    notes = request.form.get('notes', '').strip()

    if not name:
        flash('اسم المسجد مطلوب', 'danger')
        return redirect(url_for('mosques'))

    if Mosque.query.filter_by(name=name).first():
        flash('يوجد مسجد مسجل بنفس هذا الاسم مسبقاً', 'warning')
        return redirect(url_for('mosques'))

    mosque = Mosque(name=name, address=address, capacity=capacity, notes=notes)
    db.session.add(mosque)
    db.session.commit()
    flash(f'تم إضافة مسجد "{name}" بنجاح', 'success')
    return redirect(url_for('mosques'))

@app.route('/mosque/<int:mosque_id>/edit', methods=['POST'])
@admin_required
def edit_mosque(mosque_id):
    mosque = db.session.get(Mosque, mosque_id)
    if not mosque:
        flash('المسجد غير موجود', 'danger')
        return redirect(url_for('mosques'))

    name = request.form.get('name', '').strip()
    if name:
        mosque.name = name
    mosque.address = request.form.get('address', '').strip()
    mosque.capacity = int(request.form.get('capacity') or 0)
    mosque.notes = request.form.get('notes', '').strip()
    db.session.commit()
    flash('تم تحديث بيانات المسجد بنجاح', 'success')
    return redirect(url_for('mosques'))

@app.route('/mosque/<int:mosque_id>/delete', methods=['POST'])
@admin_required
def delete_mosque(mosque_id):
    mosque = db.session.get(Mosque, mosque_id)
    if mosque:
        name = mosque.name
        db.session.delete(mosque)
        db.session.commit()
        flash(f'تم حذف مسجد "{name}" وجميع التعيينات المرتبطة به', 'info')
    return redirect(url_for('mosques'))


# ====================================================
# إدارة الخطباء (Khateeb Management)
# ====================================================

@app.route('/khutbas')
@admin_required
def khutbas():
    all_khatebs = Khateb.query.order_by(Khateb.is_active.asc(), Khateb.name.asc()).all()
    all_mosques = Mosque.query.all()
    mosques_dict = {m.id: m.name for m in all_mosques}
    friday_ctx = get_friday_selection_context()

    khateb_payloads = {}
    for k in all_khatebs:
        system_visited_c1 = sorted(list(set(
            a.mosque_id for a in k.assignments
            if a.cycle_number == 1 and a.status in ('confirmed', 'completed')
        )))
        khateb_payloads[k.id] = {
            'id': k.id,
            'name': k.name,
            'phone': k.phone,
            'availability_mode': k.availability_mode,
            'alternate_offset': k.alternate_offset if k.alternate_offset in (0, 1) else friday_ctx['offset_next'],
            'unavailable_dates': k.get_unavailable_dates(),
            'forbidden_mosques': k.get_forbidden_mosques(),
            'initial_visited_mosques': k.get_initial_visited_mosques(),
            'system_visited_c1': system_visited_c1,
            'current_cycle': k.current_cycle,
            'cycle_topic': k.get_active_cycle_topic(),
        }

    return render_template(
        'khutbas.html',
        khatebs=all_khatebs,
        mosques=all_mosques,
        mosques_dict=mosques_dict,
        khateb_payloads=khateb_payloads,
        **friday_ctx
    )

@app.route('/khateb/add', methods=['POST'])
@admin_required
def add_khateb():
    friday_ctx = get_friday_selection_context()
    raw_name = request.form.get('name', '')
    raw_phone = request.form.get('phone', '')
    password = request.form.get('password', '').strip() or '123456'
    availability_mode = request.form.get('availability_mode', 'always')
    if availability_mode not in ('always', 'alternate'):
        availability_mode = 'always'
    alternate_offset_raw = request.form.get('alternate_offset')
    alternate_offset = int(alternate_offset_raw) if alternate_offset_raw in ('0', '1') else friday_ctx['offset_next']
    forbidden = [int(x) for x in request.form.getlist('forbidden_mosques') if x.isdigit()]
    initial_visited = [int(x) for x in request.form.getlist('initial_visited_mosques') if x.isdigit()]
    unavailable_dates = parse_unavailable_dates_from_form(request.form)

    valid, err_msg, name, phone = validate_khateb_inputs(raw_name, raw_phone)
    if not valid:
        flash(err_msg, 'danger')
        return redirect(url_for('khutbas'))

    if Khateb.query.filter_by(phone=phone).first():
        flash('رقم الهاتف مسجل بالفعل لخطيب آخر', 'warning')
        return redirect(url_for('khutbas'))

    khateb = Khateb(
        name=name,
        phone=phone,
        is_active=1,  # مفعّل مباشرة إذا أضافه المدير
        availability_mode=availability_mode,
        alternate_offset=alternate_offset,
        forbidden_mosques=json.dumps(sorted(list(set(forbidden)))),
        initial_visited_mosques=json.dumps(sorted(list(set(initial_visited)))),
        unavailable_dates=json.dumps(unavailable_dates),
        current_cycle=1
    )
    khateb.set_cycle_topic(request.form.get('cycle_topic', ''))
    khateb.set_password(password)
    db.session.add(khateb)
    db.session.commit()
    flash(f'تم إضافة الشيخ {name} بنجاح بكلمة مرور: {password}', 'success')
    return redirect(url_for('khutbas'))

@app.route('/khateb/<int:khateb_id>/edit', methods=['POST'])
@admin_required
def edit_khateb(khateb_id):
    khateb = db.session.get(Khateb, khateb_id)
    if not khateb:
        flash('الخطيب غير موجود', 'danger')
        return redirect(url_for('khutbas'))

    raw_name = request.form.get('name', khateb.name)
    raw_phone = request.form.get('phone', khateb.phone)
    valid, err_msg, name, phone = validate_khateb_inputs(raw_name, raw_phone)
    if not valid:
        flash(err_msg, 'danger')
        return redirect(url_for('khutbas'))

    existing_other = Khateb.query.filter(Khateb.phone == phone, Khateb.id != khateb.id).first()
    if existing_other:
        flash('رقم الجوال مستخدم بالفعل لخطيب آخر', 'warning')
        return redirect(url_for('khutbas'))

    khateb.name = name
    khateb.phone = phone
    availability_mode = request.form.get('availability_mode', khateb.availability_mode)
    khateb.availability_mode = availability_mode if availability_mode in ('always', 'alternate') else 'always'
    alternate_offset_raw = request.form.get('alternate_offset')
    if alternate_offset_raw in ('0', '1'):
        khateb.alternate_offset = int(alternate_offset_raw)

    new_password = request.form.get('password', '').strip()
    if new_password:
        khateb.set_password(new_password)

    forbidden = [int(x) for x in request.form.getlist('forbidden_mosques') if x.isdigit()]
    khateb.set_forbidden_mosques(forbidden)

    initial_visited = [int(x) for x in request.form.getlist('initial_visited_mosques') if x.isdigit()]
    khateb.set_initial_visited_mosques(initial_visited)

    # تحديث تواريخ الغياب/عدم التوفر وموضوع الدورة
    khateb.set_unavailable_dates(parse_unavailable_dates_from_form(request.form))
    if 'cycle_topic' in request.form:
        khateb.set_cycle_topic(request.form.get('cycle_topic', ''))

    db.session.commit()
    flash('تم تحديث بيانات الخطيب بنجاح', 'success')
    return redirect(url_for('khutbas'))

@app.route('/khateb/<int:khateb_id>/toggle_active', methods=['POST'])
@admin_required
def toggle_active_khateb(khateb_id):
    khateb = db.session.get(Khateb, khateb_id)
    if khateb:
        khateb.is_active = 0 if khateb.is_active == 1 else 1
        db.session.commit()
        status_str = "تفعيل" if khateb.is_active == 1 else "تعطيل"
        flash(f'تم {status_str} حساب الشيخ {khateb.name}', 'success')
    return redirect(url_for('khutbas'))

@app.route('/khateb/<int:khateb_id>/set_password', methods=['POST'])
@admin_required
def admin_set_khateb_password(khateb_id):
    khateb = db.session.get(Khateb, khateb_id)
    new_pw = request.form.get('new_password', '').strip()
    if khateb and new_pw:
        khateb.set_password(new_pw)
        db.session.commit()
        flash(f'تم تعيين كلمة مرور جديدة للشيخ {khateb.name}', 'success')
    return redirect(url_for('khutbas'))

@app.route('/khateb/<int:khateb_id>/delete', methods=['POST'])
@admin_required
def delete_khateb(khateb_id):
    khateb = db.session.get(Khateb, khateb_id)
    if khateb:
        name = khateb.name
        db.session.delete(khateb)
        db.session.commit()
        flash(f'تم حذف الشيخ {name}', 'info')
    return redirect(url_for('khutbas'))


# ====================================================
# التوزيع الأسبوعي والاحتياط (Distribution & Reserves)
# ====================================================

@app.route('/')
def index():
    if session.get('role') == 'khateb':
        return redirect(url_for('my_portal'))
    return redirect(url_for('distribution'))

def get_week_schedule_data(target_date):
    """جلب التعيينات المعتمدة والمعتذرين غير المعوضين والاحتياط لجمعة محددة"""
    confirmed_assignments = Assignment.query.filter_by(
        week_date=target_date,
        status='confirmed'
    ).all()
    confirmed_mosque_ids = {a.mosque_id for a in confirmed_assignments}

    apologized_assignments = Assignment.query.filter_by(
        week_date=target_date,
        status='apologized'
    ).all()
    uncovered_apologized = [a for a in apologized_assignments if a.mosque_id not in confirmed_mosque_ids]
    assignments = sorted(
        confirmed_assignments + uncovered_apologized,
        key=lambda a: a.mosque_id
    )

    sched = WeeklySchedule.query.filter_by(week_date=target_date).first()
    reserve_khatebs = []
    if sched:
        res_ids = sched.get_reserve_khateb_ids()
        if res_ids:
            reserve_khatebs = Khateb.query.filter(Khateb.id.in_(res_ids)).all()

    return assignments, apologized_assignments, reserve_khatebs, sched


def get_unassigned_mosques(assignments, apologized_assignments, sched):
    """إرجاع المساجد التي لم يُعيَّن لها خطيب مؤكد في جمعة موزّعة (بما فيها التي اعتذر خطيبها دون بديل)"""
    if not (assignments or apologized_assignments or sched):
        return []
    confirmed_mosque_ids = {a.mosque_id for a in assignments if a.status == 'confirmed'}
    uncovered_apologized_ids = {
        a.mosque_id for a in apologized_assignments if a.mosque_id not in confirmed_mosque_ids
    }
    unassigned = []
    for m in Mosque.query.order_by(Mosque.id.asc()).all():
        if m.id not in confirmed_mosque_ids:
            unassigned.append({
                'mosque': m,
                'reason': 'اعتذر خطيبه ولم يتوفر بديل' if m.id in uncovered_apologized_ids else 'لم يتوفر خطيب متاح للتوزيع'
            })
    return unassigned


def build_whatsapp_schedule_text(target_date, assignments, unassigned_mosques, reserve_khatebs):
    """إنشاء نص جدول التوزيع والاحتياط الجاهز للنسخ والمشاركة عبر الواتساب"""
    wa_lines = [
        "🕌 *جدول توزيع خطباء الجمعة*",
        f"📅 *التاريخ:* الجمعة {target_date.strftime('%Y-%m-%d')}",
        "────────────────────"
    ]
    if assignments:
        wa_lines.append("📋 *المساجد والخطباء المكلفون:*")
        for i, a in enumerate(assignments, 1):
            status_tag = " (اعتذر)" if a.status == 'apologized' else ""
            wa_lines.append(f"{i}. *{a.mosque.name}* ⬅️ الشيخ {a.khateb.name}{status_tag}")
    else:
        wa_lines.append("لم يتم التوزيع لهذه الجمعة بعد.")

    if unassigned_mosques:
        wa_lines.append("\n⚠️ *مساجد لم يتوفر لها خطباء (بحاجة لمعالجة):*")
        for item in unassigned_mosques:
            wa_lines.append(f"🔸 {item['mosque'].name} ({item['reason']})")

    if reserve_khatebs:
        wa_lines.append("\n📋 *جدول الخطباء الاحتياطي:*")
        for r in reserve_khatebs:
            wa_lines.append(f"▫️ الشيخ {r.name}")

    wa_lines.append("\nجزاكم الله خيراً وبارك في جهودكم 🌿")
    return "\n".join(wa_lines)


def get_schedule_summaries(selected_date=None):
    """جلب ملخص جميع التوزيعات المنشأة للعرض والفلترة"""
    all_schedules = WeeklySchedule.query.order_by(WeeklySchedule.week_date.desc()).all()
    today_d = date.today()
    items = []
    for s in all_schedules:
        assigned_count = Assignment.query.filter(
            Assignment.week_date == s.week_date,
            Assignment.status == 'confirmed'
        ).count()
        reserve_count = len(s.get_reserve_khateb_ids())
        items.append({
            'week_date': s.week_date,
            'date_str': s.week_date.strftime('%Y-%m-%d'),
            'assigned_count': assigned_count,
            'reserve_count': reserve_count,
            'is_past': s.week_date < today_d,
            'is_current_view': (selected_date is not None and s.week_date == selected_date)
        })
    return all_schedules, items


@app.route('/distribution')
@admin_required
def distribution():
    target_date_str = request.args.get('date')
    if target_date_str:
        try:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        except Exception:
            target_date = engine.get_current_friday()
    else:
        target_date = engine.get_current_friday()

    assignments, apologized_assignments, reserve_khatebs, sched = get_week_schedule_data(target_date)
    unassigned_mosques = get_unassigned_mosques(assignments, apologized_assignments, sched)
    whatsapp_text = build_whatsapp_schedule_text(target_date, assignments, unassigned_mosques, reserve_khatebs)

    # جميع الأسابيع الموزعة سابقاً مع إحصائياتها للفلترة والتنقل السريع
    all_schedules, schedule_items = get_schedule_summaries(selected_date=target_date)
    today_d = date.today()
    current_friday = engine.get_current_friday()
    prev_friday = target_date - timedelta(days=7)
    date_filter = request.args.get('filter', 'all')

    return render_template(
        'distribution.html',
        target_date=target_date,
        assignments=assignments,
        apologized_assignments=apologized_assignments,
        unassigned_mosques=unassigned_mosques,
        has_distribution=bool(assignments or apologized_assignments or sched),
        reserve_khatebs=reserve_khatebs,
        whatsapp_text=whatsapp_text,
        all_schedules=all_schedules,
        schedule_items=schedule_items,
        date_filter=date_filter,
        today_d=today_d,
        current_friday=current_friday,
        prev_friday=prev_friday,
        next_friday=engine.get_next_friday(target_date)
    )

@app.route('/distribution/create', methods=['POST'])
@admin_required
def create_distribution():
    date_str = request.form.get('target_date')
    if date_str:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    else:
        target_date = engine.get_current_friday()

    success, msg, assignments, reserve_khatebs = engine.distribute_for_week(target_date)
    flash(msg, 'success' if success else 'danger')
    return redirect(url_for('distribution', date=target_date.strftime('%Y-%m-%d')))

@app.route('/distribution/delete', methods=['POST'])
@admin_required
def delete_distribution():
    """مسح توزيعة جمعة محددة بالكامل (في المستقبل أو الماضي)"""
    date_str = request.form.get('target_date', '').strip()
    redirect_date = request.form.get('redirect_date', '').strip()
    if not date_str:
        flash('يرجى تحديد تاريخ الجمعة المراد مسح توزيعها', 'danger')
        return redirect(url_for('distribution'))

    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('صيغة التاريخ غير صالحة', 'danger')
        return redirect(url_for('distribution'))

    deleted_assignments = Assignment.query.filter_by(week_date=target_date).delete()
    deleted_sched = WeeklySchedule.query.filter_by(week_date=target_date).delete()
    db.session.commit()

    if deleted_assignments or deleted_sched:
        flash(f'تم مسح توزيعة جمعة {date_str} بنجاح ({deleted_assignments} تعيين)', 'info')
    else:
        flash(f'لا توجد توزيعة مسجلة ليوم جمعة {date_str}', 'warning')

    if redirect_date and redirect_date != date_str:
        return redirect(url_for('distribution', date=redirect_date))
    return redirect(url_for('distribution', date=date_str))

@app.route('/assignment/<int:assignment_id>/apologize', methods=['POST'])
@admin_required
def admin_apologize_assignment(assignment_id):
    """تسجيل اعتذار خطيب من قبل الإدارة والبحث عن بديل تلقائياً"""
    success, msg, replacement = engine.apologize_and_reassign(assignment_id)
    flash(msg, 'success' if success else 'warning')
    a = db.session.get(Assignment, assignment_id)
    return redirect(url_for('distribution', date=a.week_date.strftime('%Y-%m-%d') if a else None))

@app.route('/assignment/<int:assignment_id>/delete', methods=['POST'])
@admin_required
def delete_assignment(assignment_id):
    a = db.session.get(Assignment, assignment_id)
    if a:
        date_str = a.week_date.strftime('%Y-%m-%d')
        db.session.delete(a)
        db.session.commit()
        flash('تم حذف التعيين', 'info')
        return redirect(url_for('distribution', date=date_str))
    return redirect(url_for('distribution'))


# ====================================================
# بوابة الخطيب الخاصة (Khateeb Mobile Portal)
# ====================================================

@app.route('/my')
@login_required
def my_portal():
    khateb = current_khateb()
    if not khateb:
        flash('الرجاء الدخول بحساب الخطيب', 'warning')
        return redirect(url_for('login'))

    today = date.today()
    # التعيين القادم
    upcoming = Assignment.query.filter(
        Assignment.khateb_id == khateb.id,
        Assignment.week_date >= today,
        Assignment.status.in_(['confirmed', 'apologized'])
    ).order_by(Assignment.week_date.asc()).first()

    # اختيار التوزيعة المعروضة للجمعة الكاملة (الافتراضي: أقرب جمعة قادمة موزعة، أو أحدث توزيعة)
    week_param = request.args.get('week', '').strip()
    selected_week_date = None
    if week_param:
        try:
            selected_week_date = datetime.strptime(week_param, '%Y-%m-%d').date()
        except ValueError:
            selected_week_date = None

    if selected_week_date is None:
        nearest_sched = WeeklySchedule.query.filter(
            WeeklySchedule.week_date >= today
        ).order_by(WeeklySchedule.week_date.asc()).first()
        if nearest_sched:
            selected_week_date = nearest_sched.week_date
        else:
            latest_sched = WeeklySchedule.query.order_by(WeeklySchedule.week_date.desc()).first()
            selected_week_date = latest_sched.week_date if latest_sched else engine.get_current_friday()

    week_assignments, week_apologized, week_reserves, week_sched = get_week_schedule_data(selected_week_date)
    week_unassigned_mosques = get_unassigned_mosques(week_assignments, week_apologized, week_sched)
    whatsapp_text = build_whatsapp_schedule_text(
        selected_week_date, week_assignments, week_unassigned_mosques, week_reserves
    )
    _, schedule_items = get_schedule_summaries(selected_date=selected_week_date)

    # إحصائيات الدورة الحالية
    allowed_mosques = khateb.get_allowed_mosques()
    total_allowed = len(allowed_mosques)
    visited_in_cycle = khateb.get_visited_mosques_in_cycle()
    visited_count = len(visited_in_cycle)
    progress_pct = int((visited_count / total_allowed * 100)) if total_allowed > 0 else 0

    all_mosques_dict = {m.id: m.name for m in Mosque.query.all()}

    return render_template(
        'my.html',
        khateb=khateb,
        upcoming=upcoming,
        selected_week_date=selected_week_date,
        week_assignments=week_assignments,
        week_reserves=week_reserves,
        week_unassigned_mosques=week_unassigned_mosques,
        whatsapp_text=whatsapp_text,
        week_has_schedule=bool(week_assignments or week_apologized or week_sched),
        schedule_items=schedule_items,
        total_allowed=total_allowed,
        visited_count=visited_count,
        progress_pct=progress_pct,
        visited_in_cycle=visited_in_cycle,
        all_mosques_dict=all_mosques_dict
    )

@app.route('/my/apologize/<int:assignment_id>', methods=['POST'])
@login_required
def my_apologize(assignment_id):
    khateb = current_khateb()
    a = db.session.get(Assignment, assignment_id)
    if not a or a.khateb_id != khateb.id:
        flash('تعيين غير صالح', 'danger')
        return redirect(url_for('my_portal'))

    success, msg, replacement = engine.apologize_and_reassign(assignment_id)
    flash('تم تسجيل اعتذارك بنجاح وإشعار النظام للبحث عن بديل.', 'info')
    return redirect(url_for('my_portal'))

@app.route('/my/undo_apologize/<int:assignment_id>', methods=['POST'])
@login_required
def my_undo_apologize(assignment_id):
    khateb = current_khateb()
    a = db.session.get(Assignment, assignment_id)
    if not a or a.khateb_id != khateb.id:
        flash('تعيين غير صالح', 'danger')
        return redirect(url_for('my_portal'))

    success, msg = engine.undo_apology(assignment_id)
    flash(msg, 'success' if success else 'danger')
    return redirect(url_for('my_portal'))

@app.route('/my/profile', methods=['GET', 'POST'])
@login_required
def my_profile():
    khateb = current_khateb()
    if not khateb:
        flash('الرجاء الدخول بحساب الخطيب', 'warning')
        return redirect(url_for('login'))

    friday_ctx = get_friday_selection_context()
    if request.method == 'POST':
        availability_mode = request.form.get('availability_mode', khateb.availability_mode)
        khateb.availability_mode = availability_mode if availability_mode in ('always', 'alternate') else 'always'

        alternate_offset_raw = request.form.get('alternate_offset')
        if alternate_offset_raw in ('0', '1'):
            khateb.alternate_offset = int(alternate_offset_raw)

        forbidden = [int(x) for x in request.form.getlist('forbidden_mosques') if x.isdigit()]
        khateb.set_forbidden_mosques(forbidden)

        initial_visited = [int(x) for x in request.form.getlist('initial_visited_mosques') if x.isdigit()]
        khateb.set_initial_visited_mosques(initial_visited)

        khateb.set_unavailable_dates(parse_unavailable_dates_from_form(request.form))
        if 'cycle_topic' in request.form:
            khateb.set_cycle_topic(request.form.get('cycle_topic', ''))

        new_pw = request.form.get('new_password', '').strip()
        if new_pw:
            khateb.set_password(new_pw)

        db.session.commit()
        flash('تم حفظ إعدادات ملفك الشخصي وتفضيلاتك بنجاح', 'success')
        return redirect(url_for('my_portal'))

    mosques = Mosque.query.all()
    system_visited_c1 = sorted(list(set(
        a.mosque_id for a in khateb.assignments
        if a.cycle_number == 1 and a.status in ('confirmed', 'completed')
    )))
    return render_template(
        'my_profile.html',
        khateb=khateb,
        mosques=mosques,
        system_visited_c1=system_visited_c1,
        **friday_ctx
    )


# ====================================================
# الإعدادات، النسخ الاحتياطي، والصيانة (Settings)
# ====================================================

@app.route('/settings')
@admin_required
def settings():
    return render_template('settings.html')

@app.route('/settings/backup/download')
@admin_required
def backup_download():
    """تنزيل نسخة احتياطية فورية من قاعدة البيانات"""
    db_file = os.path.join(INSTANCE_DIR, 'khutba_distribution.db')
    if not os.path.exists(db_file):
        flash('قاعدة البيانات غير موجودة بعد', 'danger')
        return redirect(url_for('settings'))

    backup_name = f"khutba_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    return send_file(db_file, as_attachment=True, download_name=backup_name)

def _copy_sqlite_inplace(src_path, dst_path):
    """نسخ قاعدة بيانات SQLite إلى الملف الهدف باستخدام SQLite Backup API مع الحفاظ على inode الملف"""
    import sqlite3
    for suffix in ('-wal', '-shm', '-journal'):
        sidecar = dst_path + suffix
        if os.path.exists(sidecar):
            try:
                os.remove(sidecar)
            except OSError:
                pass
    src_conn = sqlite3.connect(src_path)
    try:
        dst_conn = sqlite3.connect(dst_path)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


@app.route('/settings/backup/restore', methods=['POST'])
@admin_required
def backup_restore():
    """استعادة قاعدة البيانات من ملف مرفوع بأمان تام (مع الفحص والترحيل التلقائي)"""
    import sqlite3

    file = request.files.get('backup_file')
    if not file or not file.filename or not file.filename.lower().endswith('.db'):
        flash('يرجى اختيار ملف قاعدة بيانات صالح بصيغة .db', 'danger')
        return redirect(url_for('settings'))

    db_file = os.path.join(INSTANCE_DIR, 'khutba_distribution.db')
    staging_db = os.path.join(INSTANCE_DIR, f"upload_staging_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.db")

    try:
        file.save(staging_db)

        # 1. التحقق من سلامة ملف SQLite ووجود الجداول الأساسية قبل المساس بالقاعدة الحية
        try:
            check_conn = sqlite3.connect(staging_db)
            integrity = check_conn.execute("PRAGMA integrity_check").fetchone()
            tables = {
                r[0] for r in check_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            check_conn.close()
        except sqlite3.DatabaseError:
            flash('الملف المرفوع تالف أو ليس قاعدة بيانات SQLite صالحة', 'danger')
            return redirect(url_for('settings'))

        if not integrity or integrity[0] != 'ok' or not {'mosque', 'khateb'}.issubset(tables):
            flash('الملف المرفوع لا يحتوي على جداول النظام المطلوبة (mosque / khateb)', 'danger')
            return redirect(url_for('settings'))

        # 2. ترحيل وترقية النسخة في ملف مؤقت معزول أولاً
        migrated = migrate_legacy_sqlite_file(staging_db)
        ensure_schema(staging_db)

        # 3. حفظ نسخة أمان من القاعدة الحالية عبر SQLite Backup API
        if not app.config.get('TESTING') and os.path.exists(db_file):
            safety_name = os.path.join(INSTANCE_DIR, f"pre_restore_safety_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
            _copy_sqlite_inplace(db_file, safety_name)

        # 4. إغلاق اتصالات SQLAlchemy ثم النسخ الآمن داخل db_file مع الحفاظ على inode
        db.session.remove()
        db.engine.dispose()
        _copy_sqlite_inplace(staging_db, db_file)

        with app.app_context():
            db.create_all()
            db.session.remove()

        if migrated:
            flash('تمت استعادة قاعدة البيانات وترحيل البيانات القديمة (المساجد والخطباء والمساجد المزارة) للنظام الجديد بنجاح', 'success')
        else:
            flash('تمت استعادة قاعدة البيانات بنجاح', 'success')
        return redirect(url_for('settings'))
    except Exception as exc:
        db.session.rollback()
        flash(f'تعذر استعادة قاعدة البيانات: {exc}', 'danger')
        return redirect(url_for('settings'))
    finally:
        if os.path.exists(staging_db):
            try:
                os.remove(staging_db)
            except OSError:
                pass

@app.route('/settings/admin/password', methods=['POST'])
@admin_required
def change_admin_password():
    from werkzeug.security import generate_password_hash
    new_pw = request.form.get('new_password', '').strip()
    if new_pw:
        AppSetting.set('admin_password_hash', generate_password_hash(new_pw))
        flash('تم تغيير كلمة مرور المدير بنجاح', 'success')
    return redirect(url_for('settings'))

@app.route('/settings/reset/future', methods=['POST'])
@admin_required
def reset_future_distributions():
    """حذف التوزيعات من اليوم فصاعداً"""
    today = date.today()
    deleted = Assignment.query.filter(Assignment.week_date >= today).delete()
    WeeklySchedule.query.filter(WeeklySchedule.week_date >= today).delete()
    db.session.commit()
    flash(f'تم حذف {deleted} تعييناً مستقبلياً بنجاح', 'info')
    return redirect(url_for('settings'))

@app.route('/settings/reset/all', methods=['POST'])
@admin_required
def reset_entire_system():
    """تصفير النظام بالكامل (حذف المساجد والخطباء والتوزيعات والجداول مع أخذ نسخة أمان)"""
    db_file = os.path.join(INSTANCE_DIR, 'khutba_distribution.db')
    if not app.config.get('TESTING') and os.path.exists(db_file):
        safety_name = os.path.join(INSTANCE_DIR, f"pre_full_reset_safety_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
        shutil.copy2(db_file, safety_name)

    Assignment.query.delete()
    WeeklySchedule.query.delete()
    Khateb.query.delete()
    Mosque.query.delete()
    db.session.commit()
    AppSetting.set('skip_sample_data', '1')

    flash('تم تصفير النظام كله وحذف جميع المساجد والخطباء والتوزيعات بنجاح (مع حفظ نسخة أمان احتياطية)', 'warning')
    return redirect(url_for('settings'))


# ====================================================
# التهيئة والتشغيل
# ====================================================

def migrate_legacy_sqlite_file(db_file):
    """ترحيل قاعدة بيانات قديمة (تحتوي على حقول الموضوع أو mosques_visited) إلى الهيكل الجديد النظيف"""
    import sqlite3
    from sqlalchemy import create_engine

    if not os.path.exists(db_file):
        return False

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    def get_cols(table_name):
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        if not cursor.fetchone():
            return []
        cursor.execute(f"PRAGMA table_info({table_name})")
        return [r[1] for r in cursor.fetchall()]

    khateb_cols = get_cols('khateb')
    assignment_cols = get_cols('assignment')
    mosque_cols = get_cols('mosque')
    sched_cols = get_cols('weekly_schedule')
    setting_cols = get_cols('app_setting')

    is_legacy = ('mosques_visited' in khateb_cols) or ('khutba_topic' in assignment_cols)
    if not is_legacy:
        conn.close()
        return False

    mosques_rows = cursor.execute("SELECT * FROM mosque").fetchall() if mosque_cols else []
    khatebs_rows = cursor.execute("SELECT * FROM khateb").fetchall() if khateb_cols else []
    assign_rows = cursor.execute("SELECT * FROM assignment").fetchall() if assignment_cols else []
    sched_rows = cursor.execute("SELECT * FROM weekly_schedule").fetchall() if sched_cols else []
    setting_rows = cursor.execute("SELECT * FROM app_setting").fetchall() if setting_cols else []
    conn.close()

    temp_db = db_file + '.migrating.db'
    if os.path.exists(temp_db):
        os.remove(temp_db)

    try:
        temp_engine = create_engine(f"sqlite:///{temp_db}")
        db.metadata.create_all(bind=temp_engine)
        temp_engine.dispose()

        dst = sqlite3.connect(temp_db)
        cur = dst.cursor()

        seen_mosque_names = set()
        valid_mosque_ids = set()
        for m in mosques_rows:
            m_dict = dict(m)
            m_name = (m_dict.get('name') or '').strip() or f"مسجد {m_dict['id']}"
            if m_name in seen_mosque_names:
                m_name = f"{m_name} ({m_dict['id']})"
            seen_mosque_names.add(m_name)
            valid_mosque_ids.add(m_dict['id'])
            cur.execute(
                "INSERT INTO mosque (id, name, address, capacity, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    m_dict['id'],
                    m_name,
                    m_dict.get('address') or '',
                    m_dict.get('capacity') if m_dict.get('capacity') is not None else 0,
                    m_dict.get('notes') or '',
                    m_dict.get('created_at')
                )
            )

        seen_phones = set()
        valid_khateb_ids = set()
        for k in khatebs_rows:
            k_dict = dict(k)
            visited_raw = k_dict.get('initial_visited_mosques') or k_dict.get('mosques_visited') or '[]'
            try:
                visited_ids = sorted(list(set(int(x) for x in json.loads(visited_raw))))
            except Exception:
                visited_ids = []

            forbidden_raw = k_dict.get('forbidden_mosques') or '[]'
            try:
                forbidden_ids = sorted(list(set(int(x) for x in json.loads(forbidden_raw))))
            except Exception:
                forbidden_ids = []

            avail_mode = k_dict.get('availability_mode') or 'always'
            if avail_mode not in ('always', 'alternate'):
                avail_mode = 'always'

            alt_offset = int(k_dict.get('alternate_offset') or 0) % 2
            phone_val = normalize_phone(k_dict.get('phone') or '')
            if not phone_val or phone_val in seen_phones:
                phone_val = f"000000{k_dict['id']}"
            seen_phones.add(phone_val)
            valid_khateb_ids.add(k_dict['id'])

            cur.execute(
                """INSERT INTO khateb
                (id, name, phone, password_hash, is_active, availability_mode, alternate_offset,
                 unavailable_dates, forbidden_mosques, initial_visited_mosques, current_cycle, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    k_dict['id'],
                    (k_dict.get('name') or '').strip() or f"خطيب {k_dict['id']}",
                    phone_val,
                    k_dict.get('password_hash') or '',
                    k_dict.get('is_active') if k_dict.get('is_active') is not None else 1,
                    avail_mode,
                    alt_offset,
                    k_dict.get('unavailable_dates') or '[]',
                    json.dumps(forbidden_ids),
                    json.dumps(visited_ids),
                    k_dict.get('current_cycle') or 1,
                    k_dict.get('created_at')
                )
            )

        seen_confirmed_kw = set()
        seen_confirmed_mw = set()
        for a in assign_rows:
            a_dict = dict(a)
            if a_dict['khateb_id'] not in valid_khateb_ids or a_dict['mosque_id'] not in valid_mosque_ids:
                continue
            status = a_dict.get('status') or 'confirmed'
            w_date = str(a_dict['week_date'])
            if status == 'confirmed':
                if (a_dict['khateb_id'], w_date) in seen_confirmed_kw or (a_dict['mosque_id'], w_date) in seen_confirmed_mw:
                    status = 'cancelled'
                else:
                    seen_confirmed_kw.add((a_dict['khateb_id'], w_date))
                    seen_confirmed_mw.add((a_dict['mosque_id'], w_date))
            cur.execute(
                """INSERT INTO assignment
                (id, khateb_id, mosque_id, week_date, cycle_number, status, replacement_for_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    a_dict['id'],
                    a_dict['khateb_id'],
                    a_dict['mosque_id'],
                    a_dict['week_date'],
                    a_dict.get('cycle_number') or 1,
                    status,
                    a_dict.get('replacement_for_id') or a_dict.get('replacement_of_id'),
                    a_dict.get('created_at')
                )
            )

        for s in sched_rows:
            s_dict = dict(s)
            cur.execute(
                """INSERT INTO weekly_schedule
                (id, week_date, khateb_ids, reserve_khateb_ids, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    s_dict['id'],
                    s_dict['week_date'],
                    s_dict.get('khateb_ids') or '[]',
                    s_dict.get('reserve_khateb_ids') or '[]',
                    s_dict.get('created_at')
                )
            )

        has_skip = False
        for st in setting_rows:
            st_dict = dict(st)
            key = st_dict.get('key', '')
            if not key or key.startswith('register_token_'):
                continue
            if key == 'skip_sample_data':
                has_skip = True
            cur.execute(
                'INSERT OR REPLACE INTO app_setting ("key", value, updated_at) VALUES (?, ?, ?)',
                (key, st_dict.get('value'), st_dict.get('updated_at'))
            )

        if not has_skip:
            cur.execute(
                'INSERT OR REPLACE INTO app_setting ("key", value, updated_at) VALUES (?, ?, ?)',
                ('skip_sample_data', '1', datetime.utcnow().isoformat(sep=' '))
            )

        dst.commit()
        dst.close()
        _copy_sqlite_inplace(temp_db, db_file)
        return True
    finally:
        if os.path.exists(temp_db):
            try:
                os.remove(temp_db)
            except OSError:
                pass


def ensure_schema(db_file=None):
    """ترحيل تلقائي لقاعدة البيانات لإضافة أي أعمدة ناقصة بسلاسة"""
    import sqlite3
    if db_file is None:
        db_file = os.path.join(INSTANCE_DIR, 'khutba_distribution.db')
    if not os.path.exists(db_file):
        return
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    needed = {
        'mosque': [('notes', 'TEXT')],
        'khateb': [
            ('unavailable_dates', "TEXT DEFAULT '[]'"),
            ('current_cycle', 'INTEGER DEFAULT 1'),
            ('cycle_topic', "TEXT DEFAULT ''"),
            ('cycle_topic_number', 'INTEGER'),
            ('initial_visited_mosques', "TEXT DEFAULT '[]'")
        ],
        'assignment': [
            ('cycle_number', 'INTEGER DEFAULT 1'),
            ('replacement_for_id', 'INTEGER')
        ],
        'weekly_schedule': [
            ('reserve_khateb_ids', "TEXT DEFAULT '[]'")
        ]
    }

    for table, cols in needed.items():
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if not cursor.fetchone():
            continue
        cursor.execute(f"PRAGMA table_info({table})")
        existing = [r[1] for r in cursor.fetchall()]
        for col_name, col_type in cols:
            if col_name not in existing:
                try:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                except Exception:
                    pass
    conn.commit()
    conn.close()


def init_sample_data():
    """إضافة بيانات أولية تجريبية إن كانت قاعدة البيانات فارغة"""
    try:
        if AppSetting.get('skip_sample_data') == '1':
            return
        if Mosque.query.count() == 0:
            mosques_data = [
                {"name": "جامع الهدى", "address": "حي السلام، شارع الملك فيصل", "capacity": 500},
                {"name": "جامع النور", "address": "حي النزهة، طريق مكة", "capacity": 400},
                {"name": "مسجد التقوى", "address": "حي الروضة، شارع الأندلس", "capacity": 300},
                {"name": "جامع الفرقان", "address": "حي العزيزية، شارع التحلية", "capacity": 600},
                {"name": "مسجد الفلاح", "address": "حي المروة، شارع الأمير سلطان", "capacity": 250},
                {"name": "جامع الإحسان", "address": "حي الصفا، طريق المدينة", "capacity": 450},
            ]
            for md in mosques_data:
                db.session.add(Mosque(**md))

        if Khateb.query.count() == 0:
            khatebs_data = [
                {"name": "الشيخ أحمد بن محمد الشريف", "phone": "0501111111", "pw": "123456"},
                {"name": "الشيخ عبد الله بن سعد الغامدي", "phone": "0502222222", "pw": "123456"},
                {"name": "الشيخ فهد بن صالح القرني", "phone": "0503333333", "pw": "123456"},
                {"name": "الشيخ عمر بن عبد الرحمن الدوسري", "phone": "0504444444", "pw": "123456"},
                {"name": "الشيخ خالد بن علي القحطاني", "phone": "0505555555", "pw": "123456"},
                {"name": "الشيخ إبراهيم بن يوسف العتيبي", "phone": "0506666666", "pw": "123456"},
                {"name": "الشيخ منصور بن حمد الحربي", "phone": "0507777777", "pw": "123456"},
                {"name": "الشيخ سلطان بن ناصر الشهري", "phone": "0508888888", "pw": "123456"},
            ]
            for kd in khatebs_data:
                k = Khateb(name=kd['name'], phone=kd['phone'], is_active=1, availability_mode='always')
                k.set_password(kd['pw'])
                db.session.add(k)

        db.session.commit()
    except Exception:
        pass


migrate_legacy_sqlite_file(os.path.join(INSTANCE_DIR, 'khutba_distribution.db'))
ensure_schema()
with app.app_context():
    db.create_all()
    if not app.config.get('TESTING'):
        init_sample_data()


if __name__ == '__main__':
    app.run(debug=True, port=5000)
