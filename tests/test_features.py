# -*- coding: utf-8 -*-
"""
اختبارات التحقق من الملاحظات الست الجديدة في نظام موزّع الجمعة
"""
import unittest
from datetime import date, timedelta

from app import app, get_friday_selection_context
from models import db, Mosque, Khateb, Assignment, WeeklySchedule, AppSetting
from engine import DistributionEngine


class TestRequestedFeatures(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.app_context = app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()
        self.client = app.test_client()
        self.engine = DistributionEngine()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def login_as_admin(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'admin'
            sess['role'] = 'admin'
            sess['name'] = 'مدير النظام'

    def login_as_khateb(self, khateb):
        with self.client.session_transaction() as sess:
            sess['user_id'] = khateb.id
            sess['role'] = 'khateb'
            sess['khateb_id'] = khateb.id
            sess['name'] = khateb.name

    def create_mosques_and_khatebs(self, num_mosques=4, num_khatebs=4):
        mosques = []
        for i in range(num_mosques):
            m = Mosque(name=f"جامع الاختبار {i+1}", address=f"حي {i+1}")
            db.session.add(m)
            mosques.append(m)

        khatebs = []
        names = [
            "الشيخ أحمد علي",
            "الشيخ عبد الله سعد",
            "الشيخ محمد حسن",
            "الشيخ عمر خالد",
            "الشيخ إبراهيم يوسف",
            "الشيخ فهد صالح",
        ]
        for i in range(num_khatebs):
            k = Khateb(
                name=names[i % len(names)],
                phone=f"050000010{i+1}",
                is_active=1,
                availability_mode='always',
                current_cycle=1
            )
            k.set_password('123456')
            db.session.add(k)
            khatebs.append(k)

        db.session.commit()
        return mosques, khatebs

    # 1. رؤية جميع التوزيعات الأقدم والأحدث مع أزرار الفلترة
    def test_multiple_distributions_visible_and_filterable(self):
        self.create_mosques_and_khatebs(num_mosques=3, num_khatebs=3)
        self.login_as_admin()

        friday_1 = self.engine.get_current_friday()
        friday_2 = friday_1 + timedelta(days=7)
        past_friday = friday_1 - timedelta(days=14)

        self.engine.distribute_for_week(past_friday)
        self.engine.distribute_for_week(friday_1)
        self.engine.distribute_for_week(friday_2)

        # عند عرض الأسبوع الثاني، يجب أن يظل الأسبوع الأول والأقدم ظاهرين في سجل التوزيعات والفلتر
        resp = self.client.get(f'/distribution?date={friday_2.strftime("%Y-%m-%d")}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn(friday_1.strftime('%Y-%m-%d'), html)
        self.assertIn(friday_2.strftime('%Y-%m-%d'), html)
        self.assertIn(past_friday.strftime('%Y-%m-%d'), html)
        self.assertIn('scheduleFilterGroup', html)
        self.assertIn('القادمة (2)', html)
        self.assertIn('السابقة (1)', html)

        # الانتقال إلى التوزيعة الأقدم
        resp_old = self.client.get(f'/distribution?date={friday_1.strftime("%Y-%m-%d")}')
        self.assertEqual(resp_old.status_code, 200)
        self.assertIn(f'جدول توزيع جمعة: <span class="text-success">{friday_1.strftime("%Y-%m-%d")}</span>', resp_old.get_data(as_text=True))

    # 2. منع الأرقام في حقل الاسم ومنع الحروف في حقل الجوال
    def test_name_and_phone_validation(self):
        self.login_as_admin()

        # رقم في حقل الاسم -> مرفوض
        resp = self.client.post('/khateb/add', data={
            'name': '0501234567',
            'phone': '0501112223',
            'password': '123456',
            'availability_mode': 'always'
        }, follow_redirects=True)
        self.assertIn('لا يمكن إدخال أرقام في حقل اسم الخطيب', resp.get_data(as_text=True))
        self.assertEqual(Khateb.query.count(), 0)

        # اسم به أرقام -> مرفوض
        resp2 = self.client.post('/khateb/add', data={
            'name': 'الشيخ أحمد 123',
            'phone': '0501112223',
            'password': '123456',
            'availability_mode': 'always'
        }, follow_redirects=True)
        self.assertIn('لا يمكن إدخال أرقام في حقل اسم الخطيب', resp2.get_data(as_text=True))
        self.assertEqual(Khateb.query.count(), 0)

        # حروف في حقل الجوال -> مرفوض
        resp3 = self.client.post('/khateb/add', data={
            'name': 'الشيخ محمد علي',
            'phone': 'محمد علي',
            'password': '123456',
            'availability_mode': 'always'
        }, follow_redirects=True)
        self.assertIn('رقم الجوال غير صحيح', resp3.get_data(as_text=True))
        self.assertEqual(Khateb.query.count(), 0)

        # تجربة نفس التحقق في صفحة التسجيل الذاتي
        resp4 = self.client.post('/register', data={
            'name': '12345678',
            'phone': 'أحمد',
            'password': 'secret'
        }, follow_redirects=True)
        self.assertIn('لا يمكن إدخال أرقام في حقل اسم الخطيب', resp4.get_data(as_text=True))
        self.assertEqual(Khateb.query.count(), 0)

        # بيانات صحيحة (مع أرقام عربية في الجوال) -> مقبول ويُطبَّع الجوال
        resp5 = self.client.post('/khateb/add', data={
            'name': 'الشيخ خالد بن وليد',
            'phone': '٠٥٠٩٩٩٨٨٨٧',
            'password': '123456',
            'availability_mode': 'always'
        }, follow_redirects=True)
        self.assertEqual(Khateb.query.count(), 1)
        k = Khateb.query.first()
        self.assertEqual(k.phone, '0509998887')

    # 3. تحديد أسبوع بداية التناوب (الجمعة القادمة أم بعد القادمة)
    def test_alternate_week_start_next_vs_after_next(self):
        self.login_as_admin()
        ctx = get_friday_selection_context()
        next_fri = ctx['next_friday']
        after_next_fri = ctx['after_next_friday']
        third_fri = after_next_fri + timedelta(days=7)

        # خطيب يبدأ من الجمعة القادمة
        self.client.post('/khateb/add', data={
            'name': 'الشيخ الأول للتناوب',
            'phone': '0501010101',
            'password': '123456',
            'availability_mode': 'alternate',
            'alternate_offset': str(ctx['offset_next'])
        })
        # خطيب يبدأ من الجمعة بعد القادمة
        self.client.post('/khateb/add', data={
            'name': 'الشيخ الثاني للتناوب',
            'phone': '0502020202',
            'password': '123456',
            'availability_mode': 'alternate',
            'alternate_offset': str(ctx['offset_after_next'])
        })

        k1 = Khateb.query.filter_by(phone='0501010101').first()
        k2 = Khateb.query.filter_by(phone='0502020202').first()

        self.assertTrue(k1.is_available_for_date(next_fri))
        self.assertFalse(k1.is_available_for_date(after_next_fri))
        self.assertTrue(k1.is_available_for_date(third_fri))

        self.assertFalse(k2.is_available_for_date(next_fri))
        self.assertTrue(k2.is_available_for_date(after_next_fri))
        self.assertFalse(k2.is_available_for_date(third_fri))

    # 4 & 5. توحيد واجهة الإضافة والتعديل + اختيار أسابيع عدم الإتاحة بالاختيار
    def test_unified_modal_and_selectable_unavailable_fridays(self):
        mosques, khatebs = self.create_mosques_and_khatebs(num_mosques=2, num_khatebs=1)
        self.login_as_admin()
        ctx = get_friday_selection_context()
        f1 = ctx['upcoming_fridays'][0]['date_str']
        f3 = ctx['upcoming_fridays'][2]['date_str']

        # واجهة الخطباء تحتوي على المودال الموحد ومربعات اختيار الجمعات
        page = self.client.get('/khutbas')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('id="khatebModal"', html)
        self.assertIn('id="khatebUnifiedForm"', html)
        self.assertNotIn('addKhatebModal', html)
        self.assertIn('class="form-check-input unavailable-date-cb"', html)
        self.assertIn(f'value="{f1}"', html)

        # تعديل الخطيب عبر نفس الحقول الموحدة
        k = khatebs[0]
        resp = self.client.post(f'/khateb/{k.id}/edit', data={
            'name': 'الشيخ أحمد المعدل',
            'phone': k.phone,
            'password': 'newpass99',
            'availability_mode': 'alternate',
            'alternate_offset': str(ctx['offset_after_next']),
            'unavailable_dates': [f1, f3],
            'forbidden_mosques': [str(mosques[0].id)],
            'initial_visited_mosques': [str(mosques[1].id)]
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        updated = db.session.get(Khateb, k.id)
        self.assertEqual(updated.name, 'الشيخ أحمد المعدل')
        self.assertTrue(updated.check_password('newpass99'))
        self.assertEqual(updated.get_unavailable_dates(), sorted([f1, f3]))
        self.assertEqual(updated.get_forbidden_mosques(), [mosques[0].id])
        self.assertEqual(updated.get_initial_visited_mosques(), [mosques[1].id])

    # 6. تحديد المساجد التي زارها الخطيب مسبقاً لتُحسب من الدورة الأولى (للخطيب والمدير)
    def test_initial_visited_mosques_count_in_cycle_1_only(self):
        mosques, _ = self.create_mosques_and_khatebs(num_mosques=4, num_khatebs=0)

        # 1) تسجيل خطيب جديد يحدد أنه زار مسجد 1 ومسجد 2 مسبقاً
        resp = self.client.post('/register', data={
            'name': 'الشيخ سليم المسجل',
            'phone': '0505556667',
            'password': 'password1',
            'availability_mode': 'always',
            'initial_visited_mosques': [str(mosques[0].id), str(mosques[1].id)]
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        k = Khateb.query.filter_by(phone='0505556667').first()
        self.assertIsNotNone(k)
        k.is_active = 1
        db.session.commit()

        # التحقق من احتسابها في الدورة الأولى فقط
        self.assertEqual(k.get_visited_mosques_in_cycle(cycle=1), sorted([mosques[0].id, mosques[1].id]))
        self.assertEqual(k.get_visited_mosques_in_cycle(cycle=2), [])

        # التحقق من بوابة الخطيب (/my) تظهر 2 من أصل 4 (50%)
        self.login_as_khateb(k)
        portal_html = self.client.get('/my').get_data(as_text=True)
        self.assertIn('أنجزت خطبة في 2 مسجداً من أصل 4 مسموحة', portal_html)

        # التوزيع لأسبوعين: يجب أن يذهب فقط لمسجد 3 ومسجد 4 في الدورة 1!
        f1 = self.engine.get_current_friday()
        f2 = f1 + timedelta(days=7)
        f3 = f2 + timedelta(days=7)

        ok1, _, a1, _ = self.engine.distribute_for_week(f1)
        self.assertTrue(ok1)
        self.assertIn(a1[0].mosque_id, [mosques[2].id, mosques[3].id])
        self.assertEqual(a1[0].cycle_number, 1)

        ok2, _, a2, _ = self.engine.distribute_for_week(f2)
        self.assertTrue(ok2)
        self.assertIn(a2[0].mosque_id, [mosques[2].id, mosques[3].id])
        self.assertNotEqual(a2[0].mosque_id, a1[0].mosque_id)
        self.assertEqual(a2[0].cycle_number, 1)

        # الأسبوع الثالث: أتم الدورة الأولى (2 مسبقاً + 2 بالتوزيع = 4)، ينتقل تلقائياً للدورة 2 وتُتاح له كل المساجد الأربعة
        ok3, _, a3, _ = self.engine.distribute_for_week(f3)
        self.assertTrue(ok3)
        self.assertEqual(a3[0].cycle_number, 2)

        # التحقق من قدرة الخطيب على تعديل المساجد المزارة مسبقاً من ملفه (/my/profile)
        self.login_as_khateb(k)
        prof_resp = self.client.post('/my/profile', data={
            'availability_mode': 'always',
            'initial_visited_mosques': [str(mosques[0].id)]
        }, follow_redirects=True)
        self.assertEqual(prof_resp.status_code, 200)
        self.assertEqual(db.session.get(Khateb, k.id).get_initial_visited_mosques(), [mosques[0].id])

    # 7. إعادة بناء جدول الأسبوع تلقائياً عند اعتذار خطيبين وبقاء احتياط خطب مسبقاً في المسجد المطلوب
    def test_apology_triggers_automatic_week_rebuild_for_remaining_reserve(self):
        mosques, khatebs = self.create_mosques_and_khatebs(num_mosques=3, num_khatebs=6)
        target_friday = date(2026, 12, 11)

        # الخطيب السادس (عبد الستار) معتذر مسبقاً في 2026-12-11
        abdulsattar = khatebs[5]
        abdulsattar.name = 'الشيخ عبد الستار'
        abdulsattar.set_unavailable_dates(['2026-12-11'])

        # الخطيب الخامس (الاحتياط الأخير) زار المسجد 1 والمسجد 2 مسبقاً، فلا يصلح له إلا المسجد 3
        reserve_last = khatebs[4]
        reserve_last.set_initial_visited_mosques([mosques[0].id, mosques[1].id])
        db.session.commit()

        ok, msg, assignments, reserves = self.engine.distribute_for_week(target_friday)
        self.assertTrue(ok)
        self.assertEqual(len(assignments), 3)
        self.assertEqual(len(reserves), 2)
        self.assertIn(reserve_last.id, [r.id for r in reserves])
        self.assertNotIn(abdulsattar.id, [a.khateb_id for a in assignments])
        self.assertNotIn(abdulsattar.id, [r.id for r in reserves])

        # اعتذار خطيب المسجد 1 -> يتم تعويضه مباشرة بالاحتياط الأول
        assign_m1 = Assignment.query.filter_by(
            week_date=target_friday, mosque_id=mosques[0].id, status='confirmed'
        ).first()
        ok_ap1, _, rep1 = self.engine.apologize_and_reassign(assign_m1.id)
        self.assertTrue(ok_ap1)
        self.assertIsNotNone(rep1)

        # اعتذار خطيب المسجد 2 -> المتبقي في الاحتياط (reserve_last) خطب في المسجد 2 مسبقاً!
        # يجب إعادة بناء جدول الأسبوع تلقائياً وتوزيع reserve_last في المسجد 3 ونقل خطيب المسجد 3 إلى المسجد 2
        assign_m2 = Assignment.query.filter_by(
            week_date=target_friday, mosque_id=mosques[1].id, status='confirmed'
        ).first()
        ok_ap2, msg_ap2, rep2 = self.engine.apologize_and_reassign(assign_m2.id)
        self.assertTrue(ok_ap2)
        self.assertIsNotNone(rep2, f"يجب تعيين بديل بعد إعادة بناء الجدول: {msg_ap2}")

        confirmed_after = Assignment.query.filter_by(
            week_date=target_friday, status='confirmed'
        ).all()
        self.assertEqual(len(confirmed_after), 3, "يجب تغطية المساجد الثلاثة جميعها بعد إعادة البناء")
        confirmed_khateb_ids = {a.khateb_id for a in confirmed_after}
        self.assertIn(reserve_last.id, confirmed_khateb_ids, "يجب توزيع الاحتياط المتبقي")
        self.assertNotIn(abdulsattar.id, confirmed_khateb_ids, "يجب استبعاد المعتذر مسبقاً (عبد الستار)")
        self.assertNotIn(assign_m1.khateb_id, confirmed_khateb_ids, "يجب استبعاد المعتذر الأول")
        self.assertNotIn(assign_m2.khateb_id, confirmed_khateb_ids, "يجب استبعاد المعتذر الثاني")

        # التأكد من ذهاب reserve_last للمسجد 3 تحديداً (المسجد الوحيد غير المزار له)
        reserve_assign = Assignment.query.filter_by(
            week_date=target_friday, khateb_id=reserve_last.id, status='confirmed'
        ).first()
        self.assertEqual(reserve_assign.mosque_id, mosques[2].id)

        # التأكد من تحديث قائمة الاحتياط لتصبح فارغة (0)
        sched = WeeklySchedule.query.filter_by(week_date=target_friday).first()
        self.assertEqual(sched.get_reserve_khateb_ids(), [])

    # 8. تصفير النظام كله من الإعدادات ومسح أي توزيعة (في المستقبل أو الماضي)
    def test_reset_entire_system_and_delete_any_distribution(self):
        self.create_mosques_and_khatebs(num_mosques=3, num_khatebs=4)
        self.login_as_admin()
        AppSetting.set('admin_password_hash', 'test-hash-keep')

        future_friday = self.engine.get_current_friday() + timedelta(days=7)
        past_friday = self.engine.get_current_friday() - timedelta(days=14)
        self.engine.distribute_for_week(future_friday)
        self.engine.distribute_for_week(past_friday)

        # التحقق من ظهور أزرار مسح التوزيع وصفحة الإعدادات المحدثة
        dist_html = self.client.get(f'/distribution?date={past_friday.strftime("%Y-%m-%d")}').get_data(as_text=True)
        self.assertIn('/distribution/delete', dist_html)
        self.assertIn('مسح هذا التوزيع', dist_html)

        settings_html = self.client.get('/settings').get_data(as_text=True)
        self.assertIn('تصفير النظام كله', settings_html)
        self.assertNotIn('/settings/reset/cycles', settings_html)

        # مسح التوزيعة الماضية أثناء الوقوف على التوزيعة المستقبلية
        del_resp = self.client.post('/distribution/delete', data={
            'target_date': past_friday.strftime('%Y-%m-%d'),
            'redirect_date': future_friday.strftime('%Y-%m-%d')
        }, follow_redirects=False)
        self.assertEqual(del_resp.status_code, 302)
        self.assertIn(future_friday.strftime('%Y-%m-%d'), del_resp.location)
        self.assertEqual(Assignment.query.filter_by(week_date=past_friday).count(), 0)
        self.assertIsNone(WeeklySchedule.query.filter_by(week_date=past_friday).first())
        self.assertEqual(Assignment.query.filter_by(week_date=future_friday).count(), 3)

        # مسح التوزيعة الحالية (المستقبلية)
        self.client.post('/distribution/delete', data={
            'target_date': future_friday.strftime('%Y-%m-%d')
        }, follow_redirects=True)
        self.assertEqual(Assignment.query.filter_by(week_date=future_friday).count(), 0)
        self.assertIsNone(WeeklySchedule.query.filter_by(week_date=future_friday).first())

        # إعادة توزيع ثم تصفير النظام كله
        self.engine.distribute_for_week(future_friday)
        reset_resp = self.client.post('/settings/reset/all', follow_redirects=True)
        self.assertEqual(reset_resp.status_code, 200)
        self.assertEqual(Mosque.query.count(), 0)
        self.assertEqual(Khateb.query.count(), 0)
        self.assertEqual(Assignment.query.count(), 0)
        self.assertEqual(WeeklySchedule.query.count(), 0)
        # بقاء إعداد كلمة مرور المدير سليماً
        self.assertEqual(AppSetting.get('admin_password_hash'), 'test-hash-keep')

    # 9. عرض جميع التوزيعات والجدول الكامل للجمعة القادمة ونقل زر التفضيلات للأعلى في بوابة الخطيب
    def test_khateeb_portal_shows_all_distributions_full_mosques_and_top_preferences_btn(self):
        mosques, khatebs = self.create_mosques_and_khatebs(num_mosques=3, num_khatebs=4)
        f1 = self.engine.get_current_friday()
        f2 = f1 + timedelta(days=7)
        past_f = f1 - timedelta(days=7)

        self.engine.distribute_for_week(past_f)
        self.engine.distribute_for_week(f1)
        self.engine.distribute_for_week(f2)

        k = khatebs[0]
        self.login_as_khateb(k)

        resp = self.client.get('/my')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # زر تعديل التفضيلات موجود في الأعلى قبل بطاقة تكليفك ولونه واضح (btn-warning)
        pref_pos = html.find('تعديل التفضيلات والإعدادات')
        upcoming_pos = html.find('تكليفك للجمعة القادمة')
        self.assertGreater(pref_pos, -1)
        self.assertGreater(upcoming_pos, pref_pos)
        self.assertIn('btn-warning', html)

        # عرض أقرب جمعة قادمة (f1) كجدول كامل لجميع المساجد
        self.assertIn(f'جدول التوزيع الكامل لجميع المساجد:\n                            <span class="text-success">{f1.strftime("%Y-%m-%d")}</span>', html)
        for m in mosques:
            self.assertIn(m.name, html)

        # ظهور جميع التوزيعات المنشأة (القادمة والسابقة) وإمكانية التبديل إلى f2
        self.assertIn(f1.strftime('%Y-%m-%d'), html)
        self.assertIn(f2.strftime('%Y-%m-%d'), html)
        self.assertIn(past_f.strftime('%Y-%m-%d'), html)

        resp_f2 = self.client.get(f'/my?week={f2.strftime("%Y-%m-%d")}')
        self.assertEqual(resp_f2.status_code, 200)
        html_f2 = resp_f2.get_data(as_text=True)
        self.assertIn(f'<span class="text-success">{f2.strftime("%Y-%m-%d")}</span>', html_f2)
        for m in mosques:
            self.assertIn(m.name, html_f2)

    # 10. الخطيب بالتناوب (جمعة وجمعة) يحصل على أولوية أعلى للخطبة في جمعته المتاحة
    def test_alternate_khateb_gets_higher_priority_than_always(self):
        mosques, khatebs = self.create_mosques_and_khatebs(num_mosques=2, num_khatebs=4)
        ctx = get_friday_selection_context()
        target_friday = ctx['next_friday']

        # جعل الخطيب الرابع بنظام التناوب (متاح في الجمعة القادمة)
        alt_khateb = khatebs[3]
        alt_khateb.availability_mode = 'alternate'
        alt_khateb.alternate_offset = ctx['offset_next']
        db.session.commit()

        # التحقق من تفوق درجة الأولوية للخطيب بالتناوب مقارنة بالخطيب المتاح كل أسبوع
        alt_score = self.engine.compute_urgency(alt_khateb, target_friday)
        always_score = self.engine.compute_urgency(khatebs[0], target_friday)
        self.assertGreater(alt_score, always_score)

        # مع وجود 2 مسجد و 4 خطباء (2 احتياط)، يجب تعيين الخطيب بالتناوب في جمعته المتاحة
        ok, msg, assignments, reserves = self.engine.distribute_for_week(target_friday)
        self.assertTrue(ok)
        assigned_ids = {a.khateb_id for a in assignments}
        reserve_ids = {r.id for r in reserves}
        self.assertIn(alt_khateb.id, assigned_ids)
        self.assertNotIn(alt_khateb.id, reserve_ids)

    # 11. الخطيب الذي اعتذر يحصل على أولوية أعلى في الجمعة التالية ثم تعود أولويته للوضع الطبيعي بعد أن يخطب
    def test_apologized_khateb_gets_higher_priority_next_week(self):
        mosques, khatebs = self.create_mosques_and_khatebs(num_mosques=2, num_khatebs=4)
        f1 = self.engine.get_current_friday()
        f2 = f1 + timedelta(days=7)
        f3 = f2 + timedelta(days=7)

        # توزيع الأسبوع الأول
        ok1, _, a1, reserves1 = self.engine.distribute_for_week(f1)
        self.assertTrue(ok1)

        # خطيب من المعينين يعتذر في f1، بينما يوجد احتياط أيضاً لم يخطب في f1
        apologizing_assign = a1[0]
        apologized_k = db.session.get(Khateb, apologizing_assign.khateb_id)
        reserve_k = reserves1[0]
        self.engine.apologize_and_reassign(apologizing_assign.id)

        # خطيب آخر اعتذر مسبقاً عن f1 عبر unavailable_dates
        pre_apologized_k = reserves1[1]
        pre_apologized_k.set_unavailable_dates([f1.strftime('%Y-%m-%d')])
        db.session.commit()

        # في f2: كلا المعتذرين (عن تكليف f1 أو المعتذر مسبقاً عن f1) يحصلان على درجة أعلى من الاحتياط العادي الذي ارتاح فقط
        score_apologized = self.engine.compute_urgency(apologized_k, f2)
        score_pre_apologized = self.engine.compute_urgency(pre_apologized_k, f2)
        # نختبر مقارنة مباشرة مع خطيب لم يعتذر بنفس حالة الراحة (مثلاً خطيب لم يخطب في f1 دون اعتذار)
        fresh_k = Khateb(name='الشيخ الاحتياطي المحايد', phone='0508887776', is_active=1, availability_mode='always')
        fresh_k.set_password('123456')
        db.session.add(fresh_k)
        db.session.commit()
        score_neutral_rested = self.engine.compute_urgency(fresh_k, f2)

        self.assertGreater(score_apologized, score_neutral_rested)
        self.assertGreater(score_pre_apologized, score_neutral_rested)

        # عند توزيع f2 (يوجد مسجدان فقط مقابل 5 خطباء متاحين): يجب تعيين المعتذرين الاثنين على المسجدين!
        ok2, _, a2, _ = self.engine.distribute_for_week(f2)
        self.assertTrue(ok2)
        assigned_f2 = {a.khateb_id for a in a2}
        self.assertIn(apologized_k.id, assigned_f2)
        self.assertIn(pre_apologized_k.id, assigned_f2)

        # بعد أن خطبا في f2، تزول أولوية الاعتذار في f3 وتعود للحساب الطبيعي
        self.assertFalse(self.engine.has_recent_uncompensated_apology(apologized_k, f3))
        self.assertFalse(self.engine.has_recent_uncompensated_apology(pre_apologized_k, f3))


if __name__ == '__main__':
    unittest.main()
