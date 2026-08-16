"""
Unit Tests for Question Bank, Document Understanding PDF Parser, Normalizer, Validator, and Adaptive Engine.
Includes 9 mandatory test cases specified in system requirements.
"""

import unittest
from io import StringIO
from services.question_normalizer import (
    normalize_question, normalize_difficulty, normalize_question_type,
    normalize_questions
)
from services.question_validator import validate_question, validate_questions
from services.csv_parser import parse_csv
from services.pdf_parser import _parse_pdf_document_structure, _normalize_latex_math
from adaptive_engine import AdaptiveEngine


class TestQuestionNormalizer(unittest.TestCase):

    def test_difficulty_mapping(self):
        self.assertEqual(normalize_difficulty("Nhận biết"), "nhan_biet")
        self.assertEqual(normalize_difficulty("hiểu"), "nhan_biet")
        self.assertEqual(normalize_difficulty("vận dụng"), "van_dung")
        self.assertEqual(normalize_difficulty("vận dụng cao"), "van_dung_cao")
        self.assertEqual(normalize_difficulty("Khó"), "van_dung_cao")

    def test_type_mapping(self):
        self.assertEqual(normalize_question_type("Trắc nghiệm"), "single")
        self.assertEqual(normalize_question_type("Đúng/Sai"), "true_false")
        self.assertEqual(normalize_question_type("Trả lời ngắn"), "short_answer")
        self.assertEqual(normalize_question_type("Tự luận"), "essay")
        self.assertEqual(normalize_question_type("Nhiều đáp án"), "multiple_choice")

    def test_normalize_question_single(self):
        raw = {
            "question_text": " Thủ đô Việt Nam là gì? ",
            "question_type": "Trắc nghiệm",
            "difficulty_level": "Nhận biết",
            "options": [
                {"text": "Hà Nội", "is_correct": True},
                {"text": "HCM", "is_correct": False}
            ]
        }
        norm = normalize_question(raw)
        self.assertEqual(norm["question_text"], "Thủ đô Việt Nam là gì?")
        self.assertEqual(norm["question_type"], "single")
        self.assertEqual(norm["difficulty_level"], "nhan_biet")
        self.assertEqual(len(norm["options"]), 2)
        self.assertTrue(norm["options"][0]["is_correct"])


class TestQuestionValidator(unittest.TestCase):

    def test_valid_question(self):
        q = normalize_question({
            "question_text": "Câu hỏi test 1?",
            "question_type": "single",
            "difficulty_level": "nhan_biet",
            "options": [
                {"text": "A", "is_correct": True},
                {"text": "B", "is_correct": False}
            ]
        })
        val = validate_question(q)
        self.assertEqual(val["status"], "valid")
        self.assertEqual(len(val["errors"]), 0)

    def test_empty_question_text(self):
        q = normalize_question({
            "question_text": "",
            "question_type": "single",
            "difficulty_level": "nhan_biet"
        })
        val = validate_question(q)
        self.assertEqual(val["status"], "error")


class Test9MandatorySystemRequirements(unittest.TestCase):

    def test_1_pdf_theory_plus_questions_ignores_theory(self):
        """Test 1: PDF with theory section + 10 questions -> Only 10 questions extracted, theory ignored."""
        lines = [
            {"text": "I. LÝ THUYẾT CƠ BẢN", "page": 0},
            {"text": "Dữ liệu là những thông tin chưa qua xử lý...", "page": 0},
            {"text": "Thông tin là sản phẩm của việc xử lý dữ liệu...", "page": 0},
        ]
        # Add 10 questions
        for i in range(1, 11):
            lines.extend([
                {"text": f"Câu {i}. Nội dung câu hỏi số {i}?", "page": 0},
                {"text": "A. Lựa chọn A", "page": 0},
                {"text": "B. Lựa chọn B", "page": 0},
                {"text": "C. Lựa chọn C", "page": 0},
                {"text": "D. Lựa chọn D", "page": 0},
                {"text": "Đáp án: A", "page": 0},
            ])

        parsed = _parse_pdf_document_structure(lines, [])
        self.assertEqual(len(parsed), 10)
        self.assertEqual(parsed[0]["question_text"], "Nội dung câu hỏi số 1?")

    def test_2_pdf_20_single_choice_questions(self):
        """Test 2: PDF with 20 single choice questions -> 20 single questions."""
        lines = []
        for i in range(1, 21):
            lines.extend([
                {"text": f"Câu {i}. Câu trắc nghiệm {i}?", "page": 0},
                {"text": "A. Phương án A", "page": 0},
                {"text": "B. Phương án B", "page": 0},
                {"text": "C. Phương án C", "page": 0},
                {"text": "D. Phương án D", "page": 0},
                {"text": "Đáp án: A", "page": 0},
            ])
        parsed = _parse_pdf_document_structure(lines, [])
        self.assertEqual(len(parsed), 20)
        for q in parsed:
            self.assertEqual(q["question_type"], "single")

    def test_3_pdf_true_false_multi_statement(self):
        """Test 3: PDF with True/False 4 sub-statements -> 1 true_false question with 4 statements (NOT 4 questions)."""
        lines = [
            {"text": "Câu 3. Cho thông tin về chuyển động vật lý sau:", "page": 0},
            {"text": "a) Vận tốc là đại lượng vectơ. (Đúng)", "page": 0},
            {"text": "b) Gia tốc luôn song song với vận tốc. (Sai)", "page": 0},
            {"text": "c) Quãng đường là đại lượng không âm.", "page": 0},
            {"text": "d) Lực tác dụng gây ra gia tốc.", "page": 0},
        ]
        parsed = _parse_pdf_document_structure(lines, [])
        self.assertEqual(len(parsed), 1)  # Must be 1 question, NOT 4!
        q = parsed[0]
        self.assertEqual(q["question_type"], "true_false")
        self.assertEqual(len(q["statements"]), 4)
        self.assertEqual(q["statements"][0]["id"], "a")

    def test_4_pdf_essay_question_no_error(self):
        """Test 4: PDF with essay question -> essay type, answer = null, no error."""
        lines = [
            {"text": "Câu 4. Tự luận: Hãy trình bày và chứng minh định lý Pythagoras trong tam giác vuông.", "page": 0},
        ]
        parsed = _parse_pdf_document_structure(lines, [])
        self.assertEqual(len(parsed), 1)
        q = parsed[0]
        norm = normalize_question(q)
        val = validate_question(norm)
        self.assertEqual(val["question_type"], "essay")
        self.assertIn(val["status"], ["valid", "warning"])  # MUST NOT be error!

    def test_5_pdf_short_answer_no_answer_key_no_error(self):
        """Test 5: PDF with short answer (no answer key) -> short_answer, answer = null, no error."""
        lines = [
            {"text": "Câu 5. Trả lời ngắn: Tính diện tích hình tròn có bán kính r = 5cm. Kết quả bằng bao nhiêu?", "page": 0},
        ]
        parsed = _parse_pdf_document_structure(lines, [])
        self.assertEqual(len(parsed), 1)
        q = parsed[0]
        norm = normalize_question(q)
        val = validate_question(norm)
        self.assertEqual(val["question_type"], "short_answer")
        self.assertIn(val["status"], ["valid", "warning"])  # MUST NOT be error!

    def test_6_pdf_image_extracted_and_linked(self):
        """Test 6: PDF with image -> image extracted and linked to question."""
        fake_images = [{"page": 0, "url": "/static/uploads/questions/img_test.png", "path": "/tmp/img_test.png"}]
        lines = [
            {"text": "Câu 6. Quan sát hình bên dưới và xác định góc nghiêng:", "page": 0},
            {"text": "A. 30 độ", "page": 0},
            {"text": "B. 45 độ", "page": 0},
        ]
        parsed = _parse_pdf_document_structure(lines, fake_images)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["image_url"], "/static/uploads/questions/img_test.png")

    def test_7_pdf_math_formula_preserved(self):
        """Test 7: PDF with math formula -> LaTeX preserved and normalized."""
        lines = [
            {"text": "Câu 7. Tìm nghiệm của phương trình x^2 + 2x + 1 = 0", "page": 0},
            {"text": "A. x = -1", "page": 0},
            {"text": "B. x = 1", "page": 0},
        ]
        parsed = _parse_pdf_document_structure(lines, [])
        self.assertEqual(len(parsed), 1)
        self.assertIn("$", parsed[0]["question_text"])  # Normalized with LaTeX delimiters

    def test_8_pdf_theory_questions_answers_solutions_filters_non_questions(self):
        """Test 8: PDF with Theory, Questions, Answers, Solutions -> Only actual questions imported."""
        lines = [
            {"text": "I. KIẾN THỨC CƠ BẢN", "page": 0},
            {"text": "Định nghĩa về lực và gia tốc...", "page": 0},
            {"text": "Câu 1. Lực là gì?", "page": 0},
            {"text": "A. Đại lượng vectơ", "page": 0},
            {"text": "B. Đại lượng vô hướng", "page": 0},
            {"text": "Đáp án: A", "page": 0},
            {"text": "BẢNG ĐÁP ÁN", "page": 0},
            {"text": "1.A 2.B 3.C", "page": 0},
            {"text": "LỜI GIẢI CHI TIẾT", "page": 0},
            {"text": "Câu 1: Lực tác dụng gây ra gia tốc...", "page": 0},
            {"text": "Câu 2. Gia tốc có đơn vị là gì?", "page": 0},
            {"text": "A. m/s2", "page": 0},
            {"text": "B. m/s", "page": 0},
        ]
        parsed = _parse_pdf_document_structure(lines, [])
        self.assertEqual(len(parsed), 2)  # Only 2 questions (Câu 1 & Câu 2)
        self.assertEqual(parsed[0]["question_text"], "Lực là gì?")
        self.assertEqual(parsed[1]["question_text"], "Gia tốc có đơn vị là gì?")

    def test_9_preview_inline_edit_resolves_error(self):
        """Test 9: Question with error in Preview, teacher edits inline -> Error resolved and question becomes valid."""
        # Initial bad question (missing text & invalid type)
        bad_q = normalize_question({"question_text": "", "question_type": "invalid"})
        val_bad = validate_question(bad_q)
        self.assertEqual(val_bad["status"], "error")

        # Teacher edits inline via edit modal
        bad_q["question_text"] = "Câu hỏi đã được giáo viên sửa trực tiếp!"
        bad_q["question_type"] = "single"
        bad_q["options"] = [
            {"text": "Phương án A", "is_correct": True},
            {"text": "Phương án B", "is_correct": False}
        ]

        val_fixed = validate_question(bad_q)
        self.assertEqual(val_fixed["status"], "valid")
        self.assertEqual(len(val_fixed["errors"]), 0)


class TestCSVParser(unittest.TestCase):

    def test_parse_csv(self):
        csv_data = (
            "question_text,question_type,difficulty_level,option_a,option_b,option_c,option_d,correct_answer,explanation\n"
            '"Thủ đô là gì?",single,nhan_biet,"Hà Nội","HCM","Đà Nẵng","Cần Thơ",A,"Hà Nội là thủ đô"\n'
        )
        stream = StringIO(csv_data)
        parsed = parse_csv(stream)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["question_text"], "Thủ đô là gì?")
        self.assertEqual(len(parsed[0]["options"]), 4)
        self.assertTrue(parsed[0]["options"][0]["is_correct"])


class TestAdaptiveEngine(unittest.TestCase):

    def test_recommend_difficulty_standard(self):
        profile = {"adaptive_difficulty": "standard", "truefalse_accuracy": 50, "short_answer_accuracy": 50}
        rec = AdaptiveEngine.recommend_difficulty(profile)
        self.assertEqual(rec["level"], "standard")
        self.assertEqual(rec["diff_config"]["nhan_biet"], 40)
        self.assertEqual(rec["diff_config"]["van_dung"], 40)
        self.assertEqual(rec["diff_config"]["van_dung_cao"], 20)

    def test_recommend_difficulty_challenge(self):
        profile = {"adaptive_difficulty": "challenge", "truefalse_accuracy": 50, "short_answer_accuracy": 50}
        rec = AdaptiveEngine.recommend_difficulty(profile)
        self.assertEqual(rec["level"], "challenge")
        self.assertEqual(rec["diff_config"]["van_dung_cao"], 40)


class TestMultiFormatParsers(unittest.TestCase):

    def test_parse_aiken_format(self):
        from services.aiken_parser import parse_aiken
        aiken_text = """
Cho hàm số f(x) = x^2 + 1. f(2) bằng bao nhiêu?
A. 3
B. 4
C. 5
D. 6
ANSWER: C
"""
        parsed = parse_aiken(aiken_text)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["question_text"], "Cho hàm số f(x) = x^2 + 1. f(2) bằng bao nhiêu?")
        self.assertEqual(len(parsed[0]["options"]), 4)
        self.assertTrue(parsed[0]["options"][2]["is_correct"])

    def test_parse_gift_format_single(self):
        from services.gift_parser import parse_gift
        gift_text = "Thủ đô của Việt Nam là gì? {=Hà Nội ~Hồ Chí Minh ~Đà Nẵng}"
        parsed = parse_gift(gift_text)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["question_type"], "single")
        self.assertEqual(len(parsed[0]["options"]), 3)
        self.assertTrue(parsed[0]["options"][0]["is_correct"])

    def test_parse_gift_format_essay(self):
        from services.gift_parser import parse_gift
        gift_text = "Hãy viết một đoạn văn ngắn miêu tả vẻ đẹp của Vịnh Hạ Long. {}"
        parsed = parse_gift(gift_text)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["question_type"], "essay")

    def test_docx_omml_math_conversion(self):
        from services.docx_parser import _omml_to_latex
        import xml.etree.ElementTree as ET
        omml_xml = '<m:f xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:e><m:r><m:t>x</m:t></m:r></m:e><m:e><m:r><m:t>2</m:t></m:r></m:e></m:f>'
        elem = ET.fromstring(omml_xml)
        latex = _omml_to_latex(elem)
        self.assertEqual(latex, "\\frac{x}{2}")

    def test_duplicate_detection(self):
        from services.question_validator import validate_questions
        class MockBankQuestion:
            def __init__(self, text):
                self.question_text = text

        existing = [MockBankQuestion("Thủ đô của Việt Nam là gì?")]
        imported = normalize_questions([{
            "question_text": "Thủ đô của Việt Nam là gì?",
            "question_type": "single",
            "options": [{"text": "Hà Nội", "is_correct": True}]
        }])

        res = validate_questions(imported, existing)
        self.assertEqual(res["questions"][0]["status"], "warning")
        self.assertIn("trùng với câu hỏi đã tồn tại", res["questions"][0]["warnings"][0])


if __name__ == "__main__":
    unittest.main()
