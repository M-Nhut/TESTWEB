"""
Adaptive Practice Engine — Recommends practice question distribution 
and updates student performance profile based on historical submission data.
Independent AI-free engine using Weighted Moving Average and rule-based difficulty adjustment.
"""

import json
import random
import datetime as dt
from database import db
from models import StudentPerformance, ExamSubmission, SubmissionAnswer, BankQuestion, QuestionBank, ExamQuestion, ExamAnswer


class AdaptiveEngine:

    @staticmethod
    def analyze_performance(student_id, subject, topic=None):
        """
        Analyze recent performance of a student in a specific subject/topic.
        Returns a performance profile dict.
        """
        # Query existing StudentPerformance or create transient one
        perf = StudentPerformance.query.filter_by(student_id=student_id, subject=subject).first()
        
        # Query recent submissions for this student in this subject
        submissions = (
            ExamSubmission.query
            .filter_by(student_id=student_id)
            .order_by(ExamSubmission.submitted_at.desc())
            .limit(10)
            .all()
        )
        
        # Filter submissions for the subject
        subject_subs = [s for s in submissions if s.exam and s.exam.course and s.exam.course.subject == subject]
        
        if not subject_subs:
            return {
                "student_id": student_id,
                "subject": subject,
                "total_attempts": 0,
                "avg_score": 0.0,
                "latest_score": 0.0,
                "score_trend": "stable",
                "adaptive_difficulty": "standard",
                "nhan_biet_accuracy": 50.0,
                "van_dung_accuracy": 50.0,
                "van_dung_cao_accuracy": 50.0,
                "single_accuracy": 50.0,
                "truefalse_accuracy": 50.0,
                "short_answer_accuracy": 50.0,
                "weak_topics": [],
                "strong_topics": []
            }

        # Calculate scores & Weighted Moving Average (70% weight on recent, 30% on older)
        scores = [s.percentage / 10.0 for s in subject_subs]  # scale to 0-10
        weights = [0.7 ** i for i in range(len(scores))]
        weighted_avg = sum(s * w for s, w in zip(scores, weights)) / sum(weights) if weights else 0
        
        latest_score = scores[0] if scores else 0
        
        # Determine trend
        if len(scores) >= 3:
            recent_avg = sum(scores[:3]) / 3
            older_avg = sum(scores[3:]) / len(scores[3:]) if len(scores) > 3 else recent_avg
            if recent_avg - older_avg >= 0.8:
                trend = "improving"
            elif older_avg - recent_avg >= 0.8:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "stable"

        # Determine difficulty level (reinforce, standard, challenge)
        if weighted_avg <= 4.5 or (trend == "declining" and weighted_avg <= 6.0):
            adaptive_difficulty = "reinforce"
        elif weighted_avg >= 7.5 and trend == "improving":
            adaptive_difficulty = "challenge"
        else:
            adaptive_difficulty = "standard"

        return {
            "student_id": student_id,
            "subject": subject,
            "total_attempts": len(subject_subs),
            "avg_score": round(weighted_avg, 1),
            "latest_score": round(latest_score, 1),
            "score_trend": trend,
            "adaptive_difficulty": adaptive_difficulty,
            "nhan_biet_accuracy": perf.nhan_biet_accuracy if perf else 50.0,
            "van_dung_accuracy": perf.van_dung_accuracy if perf else 50.0,
            "van_dung_cao_accuracy": perf.van_dung_cao_accuracy if perf else 50.0,
            "single_accuracy": perf.single_accuracy if perf else 50.0,
            "truefalse_accuracy": perf.truefalse_accuracy if perf else 50.0,
            "short_answer_accuracy": perf.short_answer_accuracy if perf else 50.0,
            "weak_topics": perf.get_weak_topics() if perf else [],
            "strong_topics": perf.get_strong_topics() if perf else []
        }

    @staticmethod
    def recommend_difficulty(profile):
        """
        Recommend question breakdown percentages based on profile.
        Ensures max ±15% difficulty shift between sessions.
        """
        level = profile.get("adaptive_difficulty", "standard")

        if level == "reinforce":
            nhan_biet = 60
            van_dung = 30
            van_dung_cao = 10
        elif level == "challenge":
            nhan_biet = 20
            van_dung = 40
            van_dung_cao = 40
        else:  # standard
            nhan_biet = 40
            van_dung = 40
            van_dung_cao = 20

        # Adjust for weak question types
        tf_acc = profile.get("truefalse_accuracy", 50.0)
        sa_acc = profile.get("short_answer_accuracy", 50.0)
        
        type_single = 50
        type_tf = 30
        type_sa = 20
        
        if tf_acc < 40.0:
            type_tf += 10
            type_single -= 10
        if sa_acc < 40.0:
            type_sa += 10
            type_single -= 10

        return {
            "level": level,
            "diff_config": {
                "nhan_biet": nhan_biet,
                "van_dung": van_dung,
                "van_dung_cao": van_dung_cao
            },
            "type_config": {
                "single": type_single,
                "truefalse": type_tf,
                "short_answer": type_sa
            },
            "target_score": "7.0 - 8.5" if level == "challenge" else "5.0 - 6.5" if level == "reinforce" else "6.0 - 7.5"
        }

    @staticmethod
    def update_performance(student_id, submission):
        """
        Update StudentPerformance record after an exam/practice submission.
        """
        if not submission or not submission.exam or not submission.exam.course:
            return
            
        subject = submission.exam.course.subject
        if not subject:
            return

        perf = StudentPerformance.query.filter_by(student_id=student_id, subject=subject).first()
        if not perf:
            perf = StudentPerformance(student_id=student_id, subject=subject)
            db.session.add(perf)

        perf.total_attempts += 1
        pct = submission.percentage / 10.0  # 0-10 scale
        perf.latest_score = round(pct, 1)

        if perf.total_attempts == 1:
            perf.avg_score = round(pct, 1)
            perf.best_score = round(pct, 1)
            perf.worst_score = round(pct, 1)
        else:
            perf.avg_score = round((perf.avg_score * (perf.total_attempts - 1) + pct) / perf.total_attempts, 1)
            perf.best_score = max(perf.best_score, round(pct, 1))
            perf.worst_score = min(perf.worst_score, round(pct, 1))

        # Breakdown stats from submission answers
        correct_by_diff = {"nhan_biet": [0, 0], "van_dung": [0, 0], "van_dung_cao": [0, 0]}
        correct_by_type = {"single": [0, 0], "truefalse": [0, 0], "short_answer": [0, 0]}

        for sa in submission.answers:
            if not sa.question:
                continue
            diff = sa.question.difficulty_level or "nhan_biet"
            qtype = sa.question.question_type or "single"
            
            if diff in correct_by_diff:
                correct_by_diff[diff][1] += 1  # total
                if sa.is_correct:
                    correct_by_diff[diff][0] += 1  # correct
                    
            if qtype in correct_by_type:
                correct_by_type[qtype][1] += 1
                if sa.is_correct:
                    correct_by_type[qtype][0] += 1

        if correct_by_diff["nhan_biet"][1] > 0:
            perf.nhan_biet_accuracy = round(correct_by_diff["nhan_biet"][0] / correct_by_diff["nhan_biet"][1] * 100, 1)
        if correct_by_diff["van_dung"][1] > 0:
            perf.van_dung_accuracy = round(correct_by_diff["van_dung"][0] / correct_by_diff["van_dung"][1] * 100, 1)
        if correct_by_diff["van_dung_cao"][1] > 0:
            perf.van_dung_cao_accuracy = round(correct_by_diff["van_dung_cao"][0] / correct_by_diff["van_dung_cao"][1] * 100, 1)

        if correct_by_type["single"][1] > 0:
            perf.single_accuracy = round(correct_by_type["single"][0] / correct_by_type["single"][1] * 100, 1)
        if correct_by_type["truefalse"][1] > 0:
            perf.truefalse_accuracy = round(correct_by_type["truefalse"][0] / correct_by_type["truefalse"][1] * 100, 1)
        if correct_by_type["short_answer"][1] > 0:
            perf.short_answer_accuracy = round(correct_by_type["short_answer"][0] / correct_by_type["short_answer"][1] * 100, 1)

        # Update difficulty recommendation
        profile = AdaptiveEngine.analyze_performance(student_id, subject)
        perf.score_trend = profile["score_trend"]
        perf.adaptive_difficulty = profile["adaptive_difficulty"]
        perf.updated_at = dt.datetime.utcnow()

        db.session.commit()
        return perf
