# -*- coding: utf-8 -*-
"""
نماذج قاعدة البيانات لنظام توزيع خطباء الجمعة
"""
import json
from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

EPOCH_FRIDAY = date(2024, 1, 5)  # جمعة مرجعية لحساب ترتيب الأسابيع بشكل متصل عبر السنوات


def get_friday_week_index(target_date):
    """حساب رقم الأسبوع التتابعي لجمعة معينة دون تأثر بتغيير السنة"""
    if isinstance(target_date, datetime):
        d = target_date.date()
    elif isinstance(target_date, str):
        d = datetime.strptime(target_date, '%Y-%m-%d').date()
    else:
        d = target_date
    return (d - EPOCH_FRIDAY).days // 7


class Mosque(db.Model):
    """نموذج المسجد"""
    __tablename__ = 'mosque'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    address = db.Column(db.String(255), default='')
    capacity = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    assignments = db.relationship('Assignment', backref='mosque', cascade='all, delete-orphan', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'address': self.address,
            'capacity': self.capacity,
            'notes': self.notes
        }


class Khateb(db.Model):
    """نموذج الخطيب"""
    __tablename__ = 'khateb'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Integer, default=0)  # 0: بانتظار موافقة المدير، 1: مفعّل
    availability_mode = db.Column(db.String(20), default='always')  # 'always' / 'alternate'
    alternate_offset = db.Column(db.Integer, default=0)  # 0 أو 1 لتحديد الجمع الفردية/الزوجية
    unavailable_dates = db.Column(db.Text, default='[]')  # JSON: تواريخ جمع محددة غير متاح فيها
    forbidden_mosques = db.Column(db.Text, default='[]')  # JSON: معرفات المساجد المستثناة
    initial_visited_mosques = db.Column(db.Text, default='[]')  # JSON: مساجد زارها قبل التسجيل تُحسب في الدورة الأولى
    current_cycle = db.Column(db.Integer, default=1)  # رقم الدورة الحالية (يبدأ من 1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    assignments = db.relationship('Assignment', backref='khateb', cascade='all, delete-orphan', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_forbidden_mosques(self):
        try:
            return json.loads(self.forbidden_mosques or '[]')
        except Exception:
            return []

    def set_forbidden_mosques(self, mosque_ids):
        self.forbidden_mosques = json.dumps(list(set(mosque_ids)))

    def get_initial_visited_mosques(self):
        try:
            return json.loads(self.initial_visited_mosques or '[]')
        except Exception:
            return []

    def set_initial_visited_mosques(self, mosque_ids):
        clean_ids = sorted(list(set(int(x) for x in mosque_ids)))
        self.initial_visited_mosques = json.dumps(clean_ids)

    def get_unavailable_dates(self):
        try:
            return json.loads(self.unavailable_dates or '[]')
        except Exception:
            return []

    def set_unavailable_dates(self, dates_list):
        self.unavailable_dates = json.dumps(sorted(list(set(dates_list))))

    def is_available_for_date(self, target_date):
        """فحص هل الخطيب متاح في تاريخ جمعة محدد"""
        if self.is_active != 1:
            return False

        date_str = target_date.strftime('%Y-%m-%d') if isinstance(target_date, (date, datetime)) else str(target_date)
        if date_str in self.get_unavailable_dates():
            return False

        if self.availability_mode == 'alternate':
            week_idx = get_friday_week_index(target_date)
            offset = self.alternate_offset or 0
            if ((week_idx + offset) % 2) != 0:
                return False

        return True

    def get_visited_mosques_in_cycle(self, cycle=None, exclude_week_date=None):
        """المساجد التي زارها أو عُيّن فيها الخطيب في دورته الحالية"""
        c = cycle if cycle is not None else self.current_cycle
        visited = set()
        if c == 1:
            allowed_ids = {m.id for m in self.get_allowed_mosques()}
            for mid in self.get_initial_visited_mosques():
                if mid in allowed_ids:
                    visited.add(mid)
        for a in self.assignments:
            if exclude_week_date is not None and a.week_date == exclude_week_date:
                continue
            if a.cycle_number == c and a.status in ('confirmed', 'completed'):
                visited.add(a.mosque_id)
        return sorted(visited)

    def get_allowed_mosques(self):
        """قائمة المساجد المسموح للخطيب بزيارتها (إجمالي المساجد ناقص المستثناة)"""
        forbidden = set(self.get_forbidden_mosques())
        all_mosques = Mosque.query.all()
        return [m for m in all_mosques if m.id not in forbidden]

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'is_active': self.is_active,
            'availability_mode': self.availability_mode,
            'alternate_offset': self.alternate_offset,
            'forbidden_mosques': self.get_forbidden_mosques(),
            'initial_visited_mosques': self.get_initial_visited_mosques(),
            'unavailable_dates': self.get_unavailable_dates(),
            'current_cycle': self.current_cycle,
            'visited_mosques': self.get_visited_mosques_in_cycle()
        }


class Assignment(db.Model):
    """نموذج تعيين خطيب في مسجد لجمعة محددة"""
    __tablename__ = 'assignment'
    __table_args__ = (
        db.Index(
            'idx_active_khateb_week',
            'khateb_id', 'week_date',
            unique=True,
            sqlite_where=db.text("status = 'confirmed'")
        ),
        db.Index(
            'idx_active_mosque_week',
            'mosque_id', 'week_date',
            unique=True,
            sqlite_where=db.text("status = 'confirmed'")
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    khateb_id = db.Column(db.Integer, db.ForeignKey('khateb.id'), nullable=False)
    mosque_id = db.Column(db.Integer, db.ForeignKey('mosque.id'), nullable=False)
    week_date = db.Column(db.Date, nullable=False)
    cycle_number = db.Column(db.Integer, default=1)
    status = db.Column(db.String(20), default='confirmed')  # confirmed, apologized, cancelled, completed
    replacement_for_id = db.Column(db.Integer, nullable=True)  # التعيين الأصلي الذي تم تعويضه
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'khateb_id': self.khateb_id,
            'khateb_name': self.khateb.name if self.khateb else '',
            'mosque_id': self.mosque_id,
            'mosque_name': self.mosque.name if self.mosque else '',
            'week_date': self.week_date.strftime('%Y-%m-%d'),
            'cycle_number': self.cycle_number,
            'status': self.status
        }


class WeeklySchedule(db.Model):
    """سجل التوزيع الأسبوعي شاملاً الخطباء والاحتياط"""
    __tablename__ = 'weekly_schedule'

    id = db.Column(db.Integer, primary_key=True)
    week_date = db.Column(db.Date, nullable=False, unique=True)
    khateb_ids = db.Column(db.Text, default='[]')  # المعينون
    reserve_khateb_ids = db.Column(db.Text, default='[]')  # جدول الخطباء الاحتياطي
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_khateb_ids(self):
        try:
            return json.loads(self.khateb_ids or '[]')
        except Exception:
            return []

    def get_reserve_khateb_ids(self):
        try:
            return json.loads(self.reserve_khateb_ids or '[]')
        except Exception:
            return []


class AppSetting(db.Model):
    """إعدادات التطبيق (مفتاح / قيمة)"""
    __tablename__ = 'app_setting'

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def get(key, default=None):
        item = AppSetting.query.get(key)
        return item.value if item else default

    @staticmethod
    def set(key, value):
        item = AppSetting.query.get(key)
        if not item:
            item = AppSetting(key=key)
        item.value = str(value)
        item.updated_at = datetime.utcnow()
        db.session.add(item)
        db.session.commit()
        return item
