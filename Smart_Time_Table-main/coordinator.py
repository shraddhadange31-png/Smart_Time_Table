# coordinator.py[cite: 3]
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, session

coordinator_bp = Blueprint("coordinator", __name__)

DEPARTMENT_DATABASE = {
    "history": []
}


def _parse_hhmm(hhmm_str):
    parts = str(hhmm_str).strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    return hour * 60 + minute


def _fmt_hhmm(total_mins):
    total_mins %= 24 * 60
    return f"{total_mins // 60:02d}:{total_mins % 60:02d}"


def build_class_teacher_timetable(
    college_start,
    college_end,
    lecture_minutes,
    practical_minutes,
    batches,
    working_days,
    subjects,
    lunch_start="12:15",
    lunch_minutes=30,
):
    start_min = _parse_hhmm(college_start)
    end_min = _parse_hhmm(college_end)
    lunch_min = _parse_hhmm(lunch_start)

    ordered_subjects = sorted(
        subjects,
        key=lambda s: float(s.get("credits", 1)),
        reverse=True,
    )
    subject_names = [
        str(s.get("name", "")).strip()
        for s in ordered_subjects
        if str(s.get("name", "")).strip()
    ]
    if not subject_names:
        subject_names = ["General Lecture"]

    practical_names = [
        (str(s.get("practical") or f"{str(s.get('name', '')).strip()} Lab")).strip()
        for s in ordered_subjects
        if s.get("has_practical", True) and str(s.get("name", "")).strip()
    ]
    if not practical_names:
        practical_names = [f"{name} Lab" for name in subject_names]

    clean_batches = [str(b).strip() for b in batches if str(b).strip()]

    rows = []
    lec_idx = 0
    prac_rotation = 0

    for day in working_days:
        day_label = str(day).strip()
        cursor = start_min
        lunch_added = False
        day_practical_done = False

        while cursor + lecture_minutes <= end_min:
            if not lunch_added and cursor >= lunch_min:
                lunch_end = min(cursor + lunch_minutes, end_min)
                if lunch_end > cursor:
                    rows.append({
                        "day": day_label,
                        "time": f"{_fmt_hhmm(cursor)} - {_fmt_hhmm(lunch_end)}",
                        "allocation": "LUNCH BREAK",
                        "type": "Break",
                    })
                    cursor = lunch_end
                lunch_added = True
                continue

            if (
                not day_practical_done
                and cursor + practical_minutes <= end_min
                and len(clean_batches) >= 1
                and (lunch_added or cursor >= lunch_min or cursor + practical_minutes <= lunch_min)
            ):
                prac_end = cursor + practical_minutes
                batch_slots = []
                for b_idx, batch_name in enumerate(clean_batches):
                    prac_subj = practical_names[(prac_rotation + b_idx) % len(practical_names)]
                    batch_slots.append(f"{prac_subj}-{batch_name}")

                rows.append({
                    "day": day_label,
                    "time": f"{_fmt_hhmm(cursor)} - {_fmt_hhmm(prac_end)}",
                    "allocation": " / ".join(batch_slots),
                    "type": "Practical",
                })
                cursor = prac_end
                prac_rotation += 1
                day_practical_done = True
                continue

            lec_end = cursor + lecture_minutes
            if not lunch_added and cursor < lunch_min < lec_end:
                lec_end = lunch_min

            subj_name = subject_names[lec_idx % len(subject_names)]
            rows.append({
                "day": day_label,
                "time": f"{_fmt_hhmm(cursor)} - {_fmt_hhmm(lec_end)}",
                "allocation": subj_name,
                "type": "Lecture",
            })
            cursor = lec_end
            lec_idx += 1

    markdown_lines = [
        "| Day | Time Slot | Subject / Practical Batches | Type |",
        "|-----|-----------|------------------------------|------|",
    ]
    for r in rows:
        markdown_lines.append(
            f"| {r['day']} | {r['time']} | {r['allocation']} | {r['type']} |"
        )

    return rows, "\n".join(markdown_lines)


@coordinator_bp.route("/api/professor/class-teacher/submit", methods=["POST"])
def submit_class_teacher_inputs():
    if session.get("user_role") != "professor" or not session.get("professor_username"):
        return jsonify({"success": False, "message": "Please log in as a professor first."}), 401

    data = request.json or {}
    required = [
        "college_start",
        "college_end",
        "lecture_minutes",
        "practical_minutes",
        "batches",
        "working_days",
        "subjects",
    ]
    if any(not data.get(key) for key in required):
        return jsonify({"success": False, "message": "Please complete all required timetable details."}), 400
    if not isinstance(data.get("working_days"), list) or not data["working_days"]:
        return jsonify({"success": False, "message": "Select at least one working day."}), 400
    if not isinstance(data.get("subjects"), list) or not data["subjects"]:
        return jsonify({"success": False, "message": "Add at least one subject with its credits."}), 400
    if data.get("college_end", "") <= data.get("college_start", ""):
        return jsonify({"success": False, "message": "College end time must be later than college start time."}), 400

    try:
        lecture_minutes = int(data.get("lecture_minutes"))
        practical_minutes = int(data.get("practical_minutes"))
        batch_count = int(data.get("batch_count", len(data.get("batches", []))))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Lecture, practical and batch values must be valid numbers."}), 400

    batches = [str(b).strip() for b in data.get("batches", []) if str(b).strip()]
    if lecture_minutes <= 0 or practical_minutes <= 0 or batch_count <= 0 or batch_count != len(batches):
        return jsonify({"success": False, "message": "Check slot durations and ensure batch names match the batch count."}), 400

    if any(not str(item.get("name", "")).strip() or float(item.get("credits", 0)) <= 0 for item in data["subjects"]):
        return jsonify({"success": False, "message": "Every subject needs a name and a positive credit value."}), 400

    rows, markdown_table = build_class_teacher_timetable(
        college_start=data["college_start"],
        college_end=data["college_end"],
        lecture_minutes=lecture_minutes,
        practical_minutes=practical_minutes,
        batches=batches,
        working_days=data["working_days"],
        subjects=data["subjects"],
    )

    return jsonify({
        "success": True,
        "status": "generated",
        "rows": rows,
        "timetable": markdown_table,
    })


@coordinator_bp.route("/api/professor/department/generate", methods=["POST"])
def generate_department_timetable():
    if session.get("user_role") != "professor" or not session.get("professor_username"):
        return jsonify({"success": False, "message": "Please log in as a professor first."}), 401

    username = session.get("professor_username", "")
    if "@" not in username:
        return jsonify({
            "success": False,
            "message": "Access Denied: Department Timetable generation requires '@' in the professor username."
        }), 403

    data = request.json or {}
    years_data = data.get("years_data", [])
    curriculum = data.get("curriculum", {})
    batch_size_limit = int(data.get("batch_size_limit", 25))
    staff_records = data.get("staff_records", [])
    college_start = data.get("college_start", "10:15")
    theory_mins = int(data.get("theory_mins", 45))
    practical_mins = int(data.get("practical_mins", 90))
    working_days = data.get("working_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"])
    labs = data.get("labs", [])

    if not years_data or not staff_records:
        return jsonify({"success": False, "message": "Years data and staff records are required."}), 400

    calculated_batches = {}
    for y_info in years_data:
        y_name = y_info["name"]
        total_students = int(y_info["capacity"])
        divs = int(y_info.get("divisions", 1))

        stud_per_div = total_students // divs
        year_batches = []
        prefix = y_name.split()[0][0].lower()
        for d_idx in range(divs):
            div_letter = chr(65 + d_idx)
            batches_in_div = max(1, stud_per_div // batch_size_limit)
            for b_num in range(1, batches_in_div + 1):
                year_batches.append(f"{y_name} Div {div_letter} - Batch {prefix}{b_num}")
        calculated_batches[y_name] = year_batches

    class_timetables = {}
    teacher_timetables = {}

    for staff in staff_records:
        teacher_timetables[staff["name"]] = {day: [] for day in working_days}

    for y_info in years_data:
        y_name = y_info["name"]
        class_timetables[y_name] = {}
        y_curr = curriculum.get(y_name, {})
        y_subjects = y_curr.get("subjects", ["General Subject"])
        y_pracs = y_curr.get("practicals", [])
        if not y_subjects:
            y_subjects = ["General Subject"]

        for day in working_days:
            day_slots = []
            slot_time_cursor = college_start

            for subj in y_subjects:
                assigned_teacher = "TBD"
                for staff in staff_records:
                    staff_year_subject = staff.get("assignments", {}).get(y_name, "").strip()
                    if staff_year_subject.lower() == subj.lower():
                        assigned_teacher = staff["name"]
                        break
                slot_info = {
                    "time": f"{slot_time_cursor} ({theory_mins}m)",
                    "subject": subj,
                    "type": "Theory",
                    "teacher": assigned_teacher,
                    "year": y_name,
                }
                day_slots.append(slot_info)
                if assigned_teacher in teacher_timetables:
                    teacher_timetables[assigned_teacher][day].append(slot_info)

            for prac in y_pracs:
                assigned_lab = labs[0]["name"] if labs else "General Lab"
                day_slots.append({
                    "time": f"Practical Session ({practical_mins}m)",
                    "subject": prac,
                    "type": "Practical",
                    "lab": assigned_lab,
                    "teacher": "Lab Instructor",
                    "year": y_name,
                })

            class_timetables[y_name][day] = day_slots

    record = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "batches": calculated_batches,
        "class_timetables": class_timetables,
        "teacher_timetables": teacher_timetables,
        "labs": labs
    }

    DEPARTMENT_DATABASE["history"].insert(0, record)
    DEPARTMENT_DATABASE["master_state"] = record

    return jsonify({
        "success": True,
        "message": "Department master timetable generated successfully!",
        "record": record
    })


@coordinator_bp.route("/api/professor/department/history", methods=["GET"])
def get_department_history():
    if session.get("user_role") != "professor" or not session.get("professor_username"):
        return jsonify({"success": False, "message": "Please log in as a professor first."}), 401
    if "@" not in session.get("professor_username", ""):
        return jsonify({"success": False, "message": "Access Denied."}), 403

    return jsonify({
        "success": True,
        "history": DEPARTMENT_DATABASE.get("history", [])
    })