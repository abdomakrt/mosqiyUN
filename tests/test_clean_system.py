# -*- coding: utf-8 -*-
"""
اختبارات شاملة للنظام النظيف (Mosqiy Clean Test Suite)
للتحقق من كافة الشروط الواردة في ملف 'تنبيهات' وقائمة الميزات:
1. استحالة تعيين خطيب في مسجدين بنفس الأسبوع.
2. استحالة تعيين خطيبين في نفس المسجد.
3. التوزيع الآلي على كافة المساجد دورة كاملة.
4. الانتقال التلقائي للدورة التالية (Cycle 2) في الأسبوع الخامس بنجاح ودون توقف.
5. جدول الخطباء الاحتياطي وعدالة التناوب.
6. نظام الاعتذار والتعويض الآلي.
7. تواريخ الغياب المحددة.
"""
import unittest
from datetime import date, timedelta
from app import app
from models import db, Mosque, Khateb, Assignment, WeeklySchedule
from engine import DistributionEngine


class TestCleanSystem(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        self.app_context = app.app_context()
        self.app_context.push()
        db.drop_all()
        db.create_all()
        self.engine = DistributionEngine()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def create_sample_data(self, num_mosques=4, num_khatebs=4):
        mosques = []
        for i in range(num_mosques):
            m = Mosque(name=f"مسجد {i+1}", address=f"حي {i+1}")
            db.session.add(m)
            mosques.append(m)

        khatebs = []
        for i in range(num_khatebs):
            k = Khateb(
                name=f"الشيخ {i+1}",
                phone=f"050000000{i+1}",
                is_active=1,
                availability_mode='always',
                current_cycle=1
            )
            k.set_password('123456')
            db.session.add(k)
            khatebs.append(k)

        db.session.commit()
        return mosques, khatebs

    def test_full_cycle_and_auto_advance_to_next_cycle(self):
        """
        التحقق من إكمال دورة كاملة على 4 مساجد في 4 أسابيع،
        ثم الانتقال التلقائي للدورة الثانية في الأسبوع الخامس بنجاح بدون توقف!
        (عكس النظام القديم الذي كان يفشل ويتوقف لطلب موضوع)
        """
        mosques, khatebs = self.create_sample_data(num_mosques=4, num_khatebs=4)
        start_date = date(2026, 12, 4)

        # الأسابيع الأربعة الأولى (الدورة 1)
        for w in range(4):
            friday = start_date + timedelta(days=7 * w)
            success, msg, assignments, reserves = self.engine.distribute_for_week(friday)
            self.assertTrue(success, f"فشل التوزيع في الأسبوع {w+1}: {msg}")
            self.assertEqual(len(assignments), 4)

            # التحقق المنطقي: لا خطيبان في نفس المسجد
            mosque_ids = [a.mosque_id for a in assignments]
            self.assertEqual(len(set(mosque_ids)), 4, "يجب عدم تكرار أي مسجد في نفس الجمعة")

            # لا خطيب في مسجدين
            khateb_ids = [a.khateb_id for a in assignments]
            self.assertEqual(len(set(khateb_ids)), 4, "يجب عدم تكرار أي خطيب في نفس الجمعة")

        # بعد 4 أسابيع، كل خطيب يجب أن يكون زار جميع المساجد الأربعة في دورته الأولى
        for k in khatebs:
            k_obj = db.session.get(Khateb, k.id)
            visited = k_obj.get_visited_mosques_in_cycle(cycle=1)
            self.assertEqual(len(visited), 4, f"الشيخ {k.name} يجب أن يكون أتم المساجد الأربعة")

        # الأسبوع الخامس: يجب أن ينجح التوزيع تلقائياً وينتقل الجميع للدورة 2!
        week_5 = start_date + timedelta(days=7 * 4)
        success_w5, msg_w5, assignments_w5, reserves_w5 = self.engine.distribute_for_week(week_5)
        self.assertTrue(success_w5, f"يجب أن ينجح التوزيع للأسبوع الخامس تلقائياً: {msg_w5}")
        self.assertEqual(len(assignments_w5), 4)

        # التحقق من أن التعيينات في الأسبوع الخامس تحمل رقم الدورة 2
        for a in assignments_w5:
            self.assertEqual(a.cycle_number, 2, "يجب أن يكون رقم دورة التعيين في الأسبوع الخامس هو 2")

    def test_reserve_khatibs_table_when_khatibs_exceed_mosques(self):
        """
        التحقق من إنشاء جدول الخطباء الاحتياطي عندما يكون عدد الخطباء أكثر من المساجد
        """
        mosques, khatebs = self.create_sample_data(num_mosques=3, num_khatebs=5)
        friday = date(2026, 12, 4)

        success, msg, assignments, reserves = self.engine.distribute_for_week(friday)
        self.assertTrue(success)
        self.assertEqual(len(assignments), 3, "يجب تعيين 3 مساجد")
        self.assertEqual(len(reserves), 2, "يجب أن يكون 2 من الخطباء في جدول الاحتياط")

        sched = WeeklySchedule.query.filter_by(week_date=friday).first()
        self.assertIsNotNone(sched)
        self.assertEqual(len(sched.get_reserve_khateb_ids()), 2)

    def test_apology_and_auto_reassignment(self):
        """
        التحقق من نظام الاعتذار والتعويض التلقائي من قائمة الاحتياط
        """
        mosques, khatebs = self.create_sample_data(num_mosques=3, num_khatebs=4)
        friday = date(2026, 12, 4)

        success, msg, assignments, reserves = self.engine.distribute_for_week(friday)
        self.assertTrue(success)
        self.assertEqual(len(reserves), 1)
        reserve_khateb_id = reserves[0].id

        # اعتذار أول خطيب معين
        assigned_to_apologize = assignments[0]
        success_apol, msg_apol, replacement = self.engine.apologize_and_reassign(assigned_to_apologize.id)
        self.assertTrue(success_apol)
        self.assertIsNotNone(replacement, "يجب تعيين الخطيب الاحتياطي بديلاً")
        self.assertEqual(replacement.id, reserve_khateb_id)

        # التأكد من تحديث حالة التعيين الأصلي إلى 'apologized'
        orig = db.session.get(Assignment, assigned_to_apologize.id)
        self.assertEqual(orig.status, 'apologized')

    def test_unavailable_dates_skipped(self):
        """
        التحقق من احترام تواريخ الغياب المحددة للخطيب
        """
        mosques, khatebs = self.create_sample_data(num_mosques=2, num_khatebs=2)
        friday = date(2026, 12, 4)

        # تحديد أن الشيخ 1 غير متاح في هذا التاريخ
        khatebs[0].set_unavailable_dates(["2026-12-04"])
        db.session.commit()

        self.assertFalse(khatebs[0].is_available_for_date(friday))
        self.assertTrue(khatebs[1].is_available_for_date(friday))

    def test_unapproved_khatib_excluded(self):
        """
        التحقق من أن الخطيب غير المعتمد (is_active = 0) لا يدخل في التوزيع نهائياً
        """
        mosques, khatebs = self.create_sample_data(num_mosques=2, num_khatebs=2)
        khatebs[0].is_active = 0
        db.session.commit()

        friday = date(2026, 12, 4)
        success, msg, assignments, reserves = self.engine.distribute_for_week(friday)
        self.assertTrue(success)
        # فقط الخطيب المعتمد يتم تعيينه
        assigned_ids = [a.khateb_id for a in assignments]
        self.assertNotIn(khatebs[0].id, assigned_ids)
        self.assertIn(khatebs[1].id, assigned_ids)

    def test_undo_apology(self):
        """
        التحقق من إمكانية التراجع عن الاعتذار إذا لم يتم تعيين بديل
        """
        mosques, khatebs = self.create_sample_data(num_mosques=2, num_khatebs=2)
        friday = date(2026, 12, 4)
        success, msg, assignments, reserves = self.engine.distribute_for_week(friday)
        self.assertTrue(success)

        a = assignments[0]
        a.status = 'apologized'
        db.session.commit()

        # التراجع
        success_undo, msg_undo = self.engine.undo_apology(a.id)
        self.assertTrue(success_undo)
        self.assertEqual(a.status, 'confirmed')


if __name__ == '__main__':
    unittest.main()
