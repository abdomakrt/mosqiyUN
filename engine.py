# -*- coding: utf-8 -*-
"""
محرك التوزيع الذكي لخطباء الجمعة
يطبق خوارزمية التراجع (Backtracking Heuristic) وعدالة التناوب والدورات التلقائية المستمرة.
"""
import json
import random
from datetime import date, datetime, timedelta
from models import db, Mosque, Khateb, Assignment, WeeklySchedule


class DistributionEngine:
    """محرك التوزيع الذكي للخطباء على المساجد"""

    ALTERNATE_PRIORITY_BONUS = 20
    APOLOGY_PRIORITY_BONUS = 20

    def __init__(self):
        pass

    def has_recent_uncompensated_apology(self, khateb, target_date):
        """
        فحص هل لدى الخطيب اعتذار سابق (اعتذار عن تكليف أو غياب مسبق) قبل التاريخ المستهدف
        ولم يخطب بعده حتى الآن، ليحصل على أولوية في جمعته القادمة.
        """
        if isinstance(target_date, str):
            target_date = datetime.strptime(target_date, '%Y-%m-%d').date()
        elif isinstance(target_date, datetime):
            target_date = target_date.date()

        last_apology = Assignment.query.filter(
            Assignment.khateb_id == khateb.id,
            Assignment.week_date < target_date,
            Assignment.status == 'apologized'
        ).order_by(Assignment.week_date.desc()).first()

        latest_apology_date = last_apology.week_date if last_apology else None

        for d_str in khateb.get_unavailable_dates():
            try:
                d_obj = datetime.strptime(d_str, '%Y-%m-%d').date()
            except ValueError:
                continue
            if d_obj < target_date:
                if latest_apology_date is None or d_obj > latest_apology_date:
                    latest_apology_date = d_obj

        if latest_apology_date is None:
            return False

        preached_after = Assignment.query.filter(
            Assignment.khateb_id == khateb.id,
            Assignment.week_date > latest_apology_date,
            Assignment.week_date < target_date,
            Assignment.status.in_(['confirmed', 'completed'])
        ).first()

        return preached_after is None

    def compute_urgency(self, khateb, target_date, visited_count=0):
        """
        حساب درجة أولوية الخطيب للخطبة في جمعة محددة:
        - الخطيب بالتناوب (جمعة يخطب وجمعة لا) يحصل على أولوية أعلى (+20)
        - الخطيب الذي اعتذر سابقاً ولم يخطب بعد اعتذاره يحصل على أولوية أعلى (+20)
        - أولوية قصوى لمن ارتاح مؤخراً (+ cr * 10) لمنع استمراره في الراحة
        - خصم لمن خطب متتالياً (- cp * 3) ليتناوب مع غيره في أخذ الراحة
        - موازنة تقدم الخطباء في الدورة (- visited_count)
        """
        cp, cr = self.compute_rest_stats(khateb.id, target_date)
        alt_bonus = self.ALTERNATE_PRIORITY_BONUS if khateb.availability_mode == 'alternate' else 0
        apology_bonus = self.APOLOGY_PRIORITY_BONUS if self.has_recent_uncompensated_apology(khateb, target_date) else 0
        return (cr * 10) - (cp * 3) + alt_bonus + apology_bonus - visited_count

    @staticmethod
    def get_current_friday():
        """الحصول على تاريخ الجمعة القادمة في المستقبل (لا يوزع في الماضي)"""
        today = date.today()
        days_ahead = 4 - today.weekday()  # الجمعة = 4
        if days_ahead <= 0:  # إذا كان اليوم جمعة أو مرّت، ننتقل للجمعة القادمة
            days_ahead += 7
        return today + timedelta(days=days_ahead)

    @staticmethod
    def get_next_friday(target_date):
        """الحصول على تاريخ الجمعة التي تلي تاريخاً معطى"""
        if isinstance(target_date, str):
            target_date = datetime.strptime(target_date, '%Y-%m-%d').date()
        return target_date + timedelta(days=7)

    @staticmethod
    def compute_rest_stats(khateb_id, target_date):
        """
        حساب إحصائيات الخطبة والراحة المتتالية للخطيب قبل التاريخ المستهدف
        يرجع: (consecutive_preach, consecutive_rest)
        """
        cur_date = target_date - timedelta(days=7)
        history = []
        for _ in range(8):
            a = Assignment.query.filter(
                Assignment.khateb_id == khateb_id,
                Assignment.week_date == cur_date,
                Assignment.status.in_(['confirmed', 'completed'])
            ).first()
            history.append(1 if a else 0)
            cur_date -= timedelta(days=7)

        consecutive_p = 0
        consecutive_r = 0
        for val in history:
            if val == 1:
                if consecutive_r == 0:
                    consecutive_p += 1
                else:
                    break
            else:
                if consecutive_p == 0:
                    consecutive_r += 1
                else:
                    break

        return consecutive_p, consecutive_r

    @staticmethod
    def get_previous_week_mosque(khateb_id, target_date):
        """معرفة المسجد الذي خطب فيه الشيخ الجمعة الماضية مباشرة لتفادي تكراره (شرط فاصل الدورات)"""
        prev_date = target_date - timedelta(days=7)
        a = Assignment.query.filter(
            Assignment.khateb_id == khateb_id,
            Assignment.week_date == prev_date,
            Assignment.status.in_(['confirmed', 'completed'])
        ).first()
        return a.mosque_id if a else None

    def get_unvisited_mosques_for_khateb(self, khateb, target_date=None, exclude_week_date=None, advance_cycle=True):
        """
        جلب المساجد المتاحة وغير المزارة للخطيب في دورته الحالية.
        إذا أتم الخطيب كل مساجده المسموحة، ينتقل تلقائياً إلى الدورة التالية (Auto-Cycling).
        """
        allowed = khateb.get_allowed_mosques()
        if not allowed:
            return []

        allowed_ids = set(m.id for m in allowed)
        visited_ids = set(khateb.get_visited_mosques_in_cycle(exclude_week_date=exclude_week_date))

        unvisited = allowed_ids - visited_ids

        # التحقق من إكمال الدورة: إذا زار جميع المساجد المسموحة له
        if len(unvisited) == 0:
            if advance_cycle:
                khateb.current_cycle += 1
                db.session.flush()
            # في الدورة الجديدة تصبح كل المساجد المسموحة متاحة من جديد
            unvisited = allowed_ids

        return sorted(list(unvisited))

    def _solve_week(self, target_friday, available_khatebs, mosques, exclude_week_date=None, advance_cycle=True):
        """
        حل مسألة مطابقة الخطباء المتاحين مع المساجد لجمعة محددة باستخدام خوارزمية التراجع مع التقليم.
        يرجع: (best_assignment_dict, eligible_khatebs)
        """
        candidate_map = {}
        urgency_map = {}
        prev_mosque_map = {}

        for khateb in available_khatebs:
            unvisited = self.get_unvisited_mosques_for_khateb(
                khateb,
                target_friday,
                exclude_week_date=exclude_week_date,
                advance_cycle=advance_cycle
            )
            if unvisited:
                candidate_map[khateb.id] = unvisited
                visited_set = set(khateb.get_visited_mosques_in_cycle(exclude_week_date=exclude_week_date))
                allowed_ids = {m.id for m in khateb.get_allowed_mosques()}
                visited_count = 0 if (allowed_ids and len(allowed_ids - visited_set) == 0) else len(visited_set)
                urgency_map[khateb.id] = self.compute_urgency(khateb, target_friday, visited_count=visited_count)
                prev_mosque_map[khateb.id] = self.get_previous_week_mosque(khateb.id, target_friday)

        eligible_khatebs = [k for k in available_khatebs if k.id in candidate_map]
        if not eligible_khatebs:
            return {}, []

        # ترتيب الخطباء حسب الأولوية العظمى للخطبة، ثم الأقل خيارات (MRV: Minimum Remaining Values)
        sorted_khatebs = sorted(
            eligible_khatebs,
            key=lambda k: (-urgency_map[k.id], len(candidate_map[k.id]))
        )

        union_mosques = set()
        for mids in candidate_map.values():
            union_mosques.update(mids)

        best_assignment = {}
        best_score = [-1, -999999]
        target_count = min(len(sorted_khatebs), len(mosques), len(union_mosques))
        steps = [0]
        max_steps = 100000

        def calculate_score(curr_assign):
            tot_urgency = sum(urgency_map.get(kid, 0) for kid in curr_assign)
            penalties = 0
            for kid, mid in curr_assign.items():
                if mid == prev_mosque_map.get(kid):
                    penalties += 50
            return [len(curr_assign), tot_urgency - penalties]

        def backtrack(index, current_assignment, used_mosques):
            steps[0] += 1
            if steps[0] > max_steps:
                return False

            score = calculate_score(current_assignment)
            if score[0] > best_score[0] or (score[0] == best_score[0] and score[1] > best_score[1]):
                best_score[0] = score[0]
                best_score[1] = score[1]
                best_assignment.clear()
                best_assignment.update(current_assignment)
                if len(best_assignment) == target_count:
                    return True

            if index >= len(sorted_khatebs):
                return False

            # تقليم الفروع التي لا يمكن أن تتجاوز أفضل حل حالي (Branch and Bound)
            remaining_khatebs = len(sorted_khatebs) - index
            remaining_mosques = len(union_mosques) - len(used_mosques)
            if len(current_assignment) + min(remaining_khatebs, remaining_mosques) < best_score[0]:
                return False

            k = sorted_khatebs[index]
            options = [mid for mid in candidate_map[k.id] if mid not in used_mosques]

            # ترتيب الخيارات بحيث نفضل المساجد التي لم يخطب فيها الجمعة الماضية
            prev_mid = prev_mosque_map.get(k.id)
            options.sort(key=lambda mid: (1 if mid == prev_mid else 0, random.random()))

            for mid in options:
                current_assignment[k.id] = mid
                used_mosques.add(mid)
                if backtrack(index + 1, current_assignment, used_mosques):
                    return True
                del current_assignment[k.id]
                used_mosques.remove(mid)

            # تجربة تخطي الخطيب الحالي لصالح خطيب آخر إذا لم تكن هناك خيارات كافية
            if backtrack(index + 1, current_assignment, used_mosques):
                return True

            return False

        backtrack(0, {}, set())
        return best_assignment, eligible_khatebs

    def distribute_for_week(self, target_friday):
        """
        توزيع الخطباء على المساجد لجمعة معينة بالخوارزمية الذكية والتناوب والاحتياط
        """
        if isinstance(target_friday, str):
            target_friday = datetime.strptime(target_friday, '%Y-%m-%d').date()

        # 1. إزالة أي تعيينات أو جدول سابق لنفس الجمعة (في حال إعادة التوزيع)
        existing_assignments = Assignment.query.filter_by(week_date=target_friday).all()
        for a in existing_assignments:
            db.session.delete(a)

        existing_sched = WeeklySchedule.query.filter_by(week_date=target_friday).first()
        if existing_sched:
            db.session.delete(existing_sched)
        db.session.flush()

        # 2. جلب المساجد والخطباء المتاحين
        mosques = Mosque.query.all()
        if not mosques:
            return False, "لا توجد مساجد مسجلة في النظام", [], []

        all_active_khatebs = Khateb.query.filter_by(is_active=1).all()
        if not all_active_khatebs:
            return False, "لا يوجد خطباء مفعلون في النظام", [], []

        for k in all_active_khatebs:
            db.session.expire(k, ['assignments'])

        # الفلترة حسب نمط التوفر وتواريخ الغياب المحددة
        available_khatebs = [k for k in all_active_khatebs if k.is_available_for_date(target_friday)]
        if not available_khatebs:
            return False, f"لا يوجد خطباء متاحون لجمعة {target_friday}", [], []

        # 3. تشغيل المحرك الذكي لإيجاد أفضل توزيع
        best_assignment, eligible_khatebs = self._solve_week(
            target_friday,
            available_khatebs,
            mosques,
            exclude_week_date=target_friday,
            advance_cycle=True
        )
        if not eligible_khatebs:
            return False, "تعذر التوزيع: لا توجد مساجد متوافقة للخطباء المتاحين", [], []

        if not best_assignment:
            return False, "لم يتم العثور على توزيع متوافق بدون تعارض", [], []

        # 4. حفظ التعيينات المنشأة
        assignments = []
        assigned_khateb_ids = set()

        for khateb_id, mosque_id in best_assignment.items():
            k_obj = db.session.get(Khateb, khateb_id)
            a = Assignment(
                khateb_id=khateb_id,
                mosque_id=mosque_id,
                week_date=target_friday,
                cycle_number=k_obj.current_cycle,
                status='confirmed'
            )
            assignments.append(a)
            assigned_khateb_ids.add(khateb_id)

        db.session.add_all(assignments)

        # 5. تحديد الخطباء في راحة (جدول الخطباء الاحتياطي)
        reserve_khateb_ids = [k.id for k in available_khatebs if k.id not in assigned_khateb_ids]

        schedule = WeeklySchedule(
            week_date=target_friday,
            khateb_ids=json.dumps(list(assigned_khateb_ids)),
            reserve_khateb_ids=json.dumps(reserve_khateb_ids)
        )
        db.session.add(schedule)
        db.session.commit()

        # إرجاع كائنات الاحتياط للعرض المباشر
        reserve_khatebs = [k for k in available_khatebs if k.id in reserve_khateb_ids]
        return True, f"تم توزيع {len(assignments)} مسجداً بنجاح وتعيين {len(reserve_khatebs)} في قائمة الاحتياط", assignments, reserve_khatebs

    def apologize_and_reassign(self, assignment_id):
        """
        تسجيل اعتذار خطيب والبحث عن بديل من الاحتياط:
        - أولاً: محاولة التعويض المباشر (1-to-1) من قائمة الاحتياط المتاحة غير المعتذرة.
        - ثانياً: إذا تعذر التعويض المباشر (مثلاً لأن الاحتياط خطب في هذا المسجد مسبقاً)،
          تُعاد هيكلة وتوزيع الأسبوع كله من الصفر تلقائياً لتوظيف الاحتياط المتبقي مع استبعاد المعتذرين وغير المتاحين.
        """
        assignment = db.session.get(Assignment, assignment_id)
        if not assignment:
            return False, "التعيين غير موجود", None

        assignment.status = 'apologized'
        db.session.flush()

        week_date = assignment.week_date
        mosque_id = assignment.mosque_id

        all_active = Khateb.query.filter_by(is_active=1).all()
        confirmed_assignments = Assignment.query.filter(
            Assignment.week_date == week_date,
            Assignment.status == 'confirmed'
        ).all()
        apologized_khateb_ids = set(
            a.khateb_id for a in Assignment.query.filter(
                Assignment.week_date == week_date,
                Assignment.status == 'apologized'
            ).all()
        )
        current_assigned_ids = set(a.khateb_id for a in confirmed_assignments)

        # 1. محاولة التعويض المباشر من الاحتياط غير المعين وغير المعتذر
        candidates = []
        for k in all_active:
            if (
                k.id != assignment.khateb_id
                and k.id not in current_assigned_ids
                and k.id not in apologized_khateb_ids
                and k.is_available_for_date(week_date)
            ):
                unvisited = self.get_unvisited_mosques_for_khateb(k, week_date, advance_cycle=False)
                if mosque_id in unvisited:
                    prev_mid = self.get_previous_week_mosque(k.id, week_date)
                    penalty = 50 if prev_mid == mosque_id else 0
                    urgency = self.compute_urgency(k, week_date) - penalty
                    candidates.append((urgency, k))

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            replacement_khateb = candidates[0][1]
            self.get_unvisited_mosques_for_khateb(replacement_khateb, week_date, advance_cycle=True)

            new_assignment = Assignment(
                khateb_id=replacement_khateb.id,
                mosque_id=mosque_id,
                week_date=week_date,
                cycle_number=replacement_khateb.current_cycle,
                status='confirmed',
                replacement_for_id=assignment.id
            )
            db.session.add(new_assignment)

            sched = WeeklySchedule.query.filter_by(week_date=week_date).first()
            if sched:
                reserves = sched.get_reserve_khateb_ids()
                if replacement_khateb.id in reserves:
                    reserves.remove(replacement_khateb.id)
                    sched.reserve_khateb_ids = json.dumps(reserves)
                assigned = sched.get_khateb_ids()
                if assignment.khateb_id in assigned:
                    assigned.remove(assignment.khateb_id)
                if replacement_khateb.id not in assigned:
                    assigned.append(replacement_khateb.id)
                sched.khateb_ids = json.dumps(assigned)

            db.session.commit()
            return True, f"تم تسجيل الاعتذار وتعيين الشيخ {replacement_khateb.name} بديلاً بنجاح", replacement_khateb

        # 2. تعذر التعويض المباشر: تجربة إعادة بناء توزيع الأسبوع كله من الصفر تلقائياً
        available_for_rebuild = [
            k for k in all_active
            if k.id not in apologized_khateb_ids and k.is_available_for_date(week_date)
        ]
        mosques = Mosque.query.all()
        old_confirmed_count = len(confirmed_assignments)

        rebuilt_map, _ = self._solve_week(
            week_date,
            available_for_rebuild,
            mosques,
            exclude_week_date=week_date,
            advance_cycle=False
        )

        if rebuilt_map and len(rebuilt_map) > old_confirmed_count:
            # نجحت إعادة البناء في تغطية عدد أكبر من المساجد وتوزيع الاحتياط المتاح
            for old_a in confirmed_assignments:
                db.session.delete(old_a)
            db.session.flush()

            for k_obj in available_for_rebuild:
                db.session.expire(k_obj, ['assignments'])

            new_assignments = []
            assigned_khateb_ids = set()
            replacement_for_target = None

            for kid, mid in rebuilt_map.items():
                k_obj = db.session.get(Khateb, kid)
                self.get_unvisited_mosques_for_khateb(
                    k_obj,
                    week_date,
                    exclude_week_date=week_date,
                    advance_cycle=True
                )
                new_a = Assignment(
                    khateb_id=kid,
                    mosque_id=mid,
                    week_date=week_date,
                    cycle_number=k_obj.current_cycle,
                    status='confirmed',
                    replacement_for_id=assignment.id if mid == mosque_id else None
                )
                new_assignments.append(new_a)
                assigned_khateb_ids.add(kid)
                if mid == mosque_id:
                    replacement_for_target = k_obj

            db.session.add_all(new_assignments)

            reserve_khateb_ids = [k.id for k in available_for_rebuild if k.id not in assigned_khateb_ids]
            sched = WeeklySchedule.query.filter_by(week_date=week_date).first()
            if not sched:
                sched = WeeklySchedule(week_date=week_date)
                db.session.add(sched)
            sched.khateb_ids = json.dumps(list(assigned_khateb_ids))
            sched.reserve_khateb_ids = json.dumps(reserve_khateb_ids)

            db.session.commit()
            if replacement_for_target:
                return (
                    True,
                    f"تعذر التعويض المباشر لأن الاحتياط خطب في المسجد مسبقاً، فتمت إعادة بناء توزيع الأسبوع تلقائياً وتعيين الشيخ {replacement_for_target.name} بديلاً بنجاح",
                    replacement_for_target
                )
            return True, "تم تسجيل الاعتذار وإعادة بناء توزيع الأسبوع تلقائياً بنجاح", None

        # 3. لم يتوفر بديل لا بالتعويض المباشر ولا بإعادة البناء
        sched = WeeklySchedule.query.filter_by(week_date=week_date).first()
        if sched:
            assigned = sched.get_khateb_ids()
            if assignment.khateb_id in assigned:
                assigned.remove(assignment.khateb_id)
                sched.khateb_ids = json.dumps(assigned)

        db.session.commit()
        return True, "تم تسجيل الاعتذار، ولم يتوفر خطيب بديل متاح متوافق حالياً", None

    def undo_apology(self, assignment_id):
        """تراجع الخطيب عن الاعتذار إذا لم يكن قد تم تعيين بديل مكانه"""
        assignment = db.session.get(Assignment, assignment_id)
        if not assignment or assignment.status != 'apologized':
            return False, "التعيين غير صالح للتراجع"

        # فحص هل تم تعيين بديل لنفس المسجد والتاريخ
        active_replacement = Assignment.query.filter_by(
            mosque_id=assignment.mosque_id,
            week_date=assignment.week_date,
            status='confirmed'
        ).first()

        if active_replacement and active_replacement.id != assignment.id:
            return False, "لا يمكن التراجع، تم تعيين خطيب بديل للمسجد بالفعل"

        assignment.status = 'confirmed'
        sched = WeeklySchedule.query.filter_by(week_date=assignment.week_date).first()
        if sched:
            assigned = sched.get_khateb_ids()
            if assignment.khateb_id not in assigned:
                assigned.append(assignment.khateb_id)
                sched.khateb_ids = json.dumps(assigned)
        db.session.commit()
        return True, "تم التراجع عن الاعتذار وتأكيد التعيين بنجاح"
