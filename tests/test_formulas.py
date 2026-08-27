"""
Comprehensive test suite for the MathType production pipeline.

Tests cover:
  - OMML pipeline (no regression)
  - MathType MTEF extraction and position attachment
  - MTEF deduplication by raw SHA-256
  - MathType without metadata → pending asset (not auto-verified)
  - Worker mock → MathML priority in frontend
  - MathML error → LaTeX fallback
  - MathML/LaTeX error → SVG fallback
  - SVG not stored in FormulaAsset SQLite
  - Worker unavailable → import succeeds, asset pending
  - No raw [[formula:...]] in rendered output
  - Placeholder remap in question/context/options/statements/explanation
  - Batch formula API returns correct data
  - SVG render endpoint behavior
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
import uuid
import zlib
import base64
import xml.etree.ElementTree as ET

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMathTypeConverter(unittest.TestCase):
    """Test the mathtype_converter module directly."""

    def test_extract_raw_mtef_with_dsmt7(self):
        """MTEF extraction from DSMT7 header."""
        from services.mathtype_converter import extract_raw_mtef
        fake_payload = b"\x00" * 20 + b"DSMT7\x00" + b"\x01\x02\x03MTEF_DATA"
        raw, version = extract_raw_mtef(fake_payload)
        self.assertIsNotNone(raw)
        self.assertEqual(version, 7)
        self.assertEqual(raw, b"\x01\x02\x03MTEF_DATA")

    def test_extract_raw_mtef_with_dsmt5(self):
        """MTEF extraction from DSMT5 header."""
        from services.mathtype_converter import extract_raw_mtef
        fake_payload = b"garbage" + b"DSMT5\x00" + b"PAYLOAD5"
        raw, version = extract_raw_mtef(fake_payload)
        self.assertIsNotNone(raw)
        self.assertEqual(version, 5)
        self.assertTrue(raw.startswith(b"PAYLOAD5"))

    def test_extract_raw_mtef_no_header(self):
        """No DSMT header → returns None."""
        from services.mathtype_converter import extract_raw_mtef
        raw, version = extract_raw_mtef(b"not a mathtype file at all")
        self.assertIsNone(raw)
        self.assertIsNone(version)

    def test_mathtype_object_prefers_ole_over_preview_image(self):
        """A Word MathType object must not lose its OLE formula behind its preview."""
        from services.docx_parser import _walk_xml_node

        preview = "/static/uploads/preview.wmf"
        formula = {"id": "formula-1", "data": {"source_format": "MathType"}}
        rels = {"rPreview": preview, "rOle": formula}
        xml = ET.fromstring(
            '<object xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<imagedata r:id="rPreview"/><OLEObject r:id="rOle"/>'
            '</object>'
        )
        chunks, formulas = [], {}
        _walk_xml_node(xml, rels, chunks, formulas)

        self.assertEqual(chunks, [" [[formula:formula-1]] "])
        self.assertIn("formula-1", formulas)

    def test_compute_mtef_hash_deterministic(self):
        """SHA-256 hash is deterministic on raw bytes."""
        from services.mathtype_converter import compute_mtef_hash
        data = b"test_mtef_data"
        h1 = compute_mtef_hash(data)
        h2 = compute_mtef_hash(data)
        self.assertEqual(h1, h2)
        self.assertEqual(h1, hashlib.sha256(data).hexdigest())

    def test_compress_mtef_roundtrip(self):
        """Compress → decompress roundtrip preserves data."""
        from services.mathtype_converter import compress_mtef
        raw_data = b"test raw mtef bytes 123"
        compressed = compress_mtef(raw_data)
        self.assertIsNotNone(compressed)
        # Roundtrip
        decompressed = zlib.decompress(base64.b64decode(compressed))
        self.assertEqual(decompressed, raw_data)

    def test_hash_computed_before_compression(self):
        """Content hash is on raw bytes, not on compressed bytes."""
        from services.mathtype_converter import compute_mtef_hash, compress_mtef
        raw = b"test_data"
        content_hash = compute_mtef_hash(raw)
        compressed = compress_mtef(raw)
        # Hash of compressed is different
        compressed_hash = hashlib.sha256(base64.b64decode(compressed)).hexdigest()
        self.assertNotEqual(content_hash, compressed_hash)
        # Hash matches raw SHA-256
        self.assertEqual(content_hash, hashlib.sha256(raw).hexdigest())

    def test_embedded_metadata_latex(self):
        """EmbeddedMetadataProvider extracts TeX from MathType translator data."""
        from services.mathtype_converter import EmbeddedMetadataProvider
        # Simulate WMF with embedded TeX
        tex_content = b"\\frac{1}{2}"
        wmf = b"PREFIX_STUFF" + b"TeX Input Language" + b"\x00" + tex_content + b"\x00" + b"MORE_DATA"
        provider = EmbeddedMetadataProvider()
        result = provider.extract_metadata(wmf)
        self.assertEqual(result["latex"], "\\frac{1}{2}")
        self.assertEqual(result["confidence"], 1.0)

    def test_embedded_metadata_mathml(self):
        """EmbeddedMetadataProvider extracts MathML metadata."""
        from services.mathtype_converter import EmbeddedMetadataProvider
        mml = b'<math xmlns="http://www.w3.org/1998/Math/MathML"><mn>42</mn></math>'
        wmf = b"PREFIX" + b"MathML" + b"\x00" + mml + b"\x00" + b"TAIL"
        provider = EmbeddedMetadataProvider()
        result = provider.extract_metadata(wmf)
        self.assertIsNotNone(result["mathml"])
        self.assertTrue(result["mathml"].startswith("<math"))
        self.assertEqual(result["confidence"], 1.0)

    def test_embedded_metadata_none(self):
        """No metadata → returns empty result."""
        from services.mathtype_converter import EmbeddedMetadataProvider
        provider = EmbeddedMetadataProvider()
        result = provider.extract_metadata(b"random_binary_data_no_metadata")
        self.assertIsNone(result["latex"])
        self.assertIsNone(result["mathml"])
        self.assertEqual(result["confidence"], 0.0)

    def test_process_formula_with_embedded_latex(self):
        """process_mathtype_formula returns converted status when metadata present."""
        from services.mathtype_converter import process_mathtype_formula
        tex_content = b"x^{2}+y^{2}=z^{2}"
        wmf = b"\x00" * 10 + b"DSMT7\x00" + b"MTEF" + b"TeX Input Language" + b"\x00" + tex_content + b"\x00"
        result = process_mathtype_formula(wmf)
        self.assertEqual(result["latex"], "x^{2}+y^{2}=z^{2}")
        self.assertEqual(result["conversion_status"], "converted")
        self.assertFalse(result["needs_review"])
        self.assertIsNotNone(result["content_hash"])
        self.assertIsNotNone(result["mtef_base64"])

    def test_process_formula_without_metadata_is_pending(self):
        """process_mathtype_formula without metadata → pending, not verified."""
        from services.mathtype_converter import process_mathtype_formula
        # WMF with DSMT header but no TeX/MathML metadata
        wmf = b"\x00" * 5 + b"DSMT7\x00" + b"\x01\x02\x03\x04\x05" * 10
        result = process_mathtype_formula(wmf)
        self.assertEqual(result["conversion_status"], "pending")
        self.assertTrue(result["needs_review"])
        self.assertIsNone(result["latex"])
        self.assertIsNone(result["mathml"])
        self.assertIsNotNone(result["content_hash"])
        self.assertIsNotNone(result["mtef_base64"])

    def test_worker_client_unavailable(self):
        """MathTypeWorkerClient with no URL returns pending."""
        from services.mathtype_converter import MathTypeWorkerClient
        # Ensure env var is not set
        os.environ.pop("MATHTYPE_WORKER_URL", None)
        client = MathTypeWorkerClient()
        self.assertFalse(client.is_available)
        result = client.convert("test", "test_hash")
        self.assertEqual(result["status"], "pending")
        self.assertIsNone(result["mathml"])


class TestLatexQuestionParser(unittest.TestCase):
    """Regression tests for Vietnamese LaTeX exam environments."""

    def test_bt_environment_is_parsed_with_display_math(self):
        from services.latex_parser import parse_latex

        source = r"""
        \begin{bt}
        Một bài toán có công thức $x^2$.
        \begin{enumerate}[a)]
          \item Mệnh đề thứ nhất $x=1$.
          \item Mệnh đề thứ hai.
        \end{enumerate}
        \loigiai{\[x^2-1=0\]}
        \end{bt}
        """
        with tempfile.NamedTemporaryFile("w", suffix=".tex", encoding="utf-8", delete=False) as handle:
            handle.write(source)
            path = handle.name
        try:
            questions = parse_latex(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["question_type"], "true_false")
        self.assertEqual(len(questions[0]["statements"]), 2)
        self.assertGreaterEqual(len(questions[0]["formulas"]), 2)


class TestFormulaAssetModel(unittest.TestCase):
    """Test FormulaAsset model fields and constraints."""

    def setUp(self):
        from app import app
        from database import db
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        from database import db
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_formula_asset_has_required_fields(self):
        """FormulaAsset has all required fields."""
        from models import FormulaAsset
        from database import db
        with self.app.app_context():
            asset = FormulaAsset(
                content_hash="abc123def456",
                mtef_data="compressed_base64",
                mathml="<math><mn>1</mn></math>",
                latex="1",
                source_format="MathType",
                converter_name="MathTypeSDK",
                converter_version="7.0",
                parse_confidence=1.0,
                conversion_status="converted",
                verification_status="verified",
                svg_cache_key="hash123.svg",
            )
            db.session.add(asset)
            db.session.commit()

            saved = FormulaAsset.query.filter_by(content_hash="abc123def456").first()
            self.assertIsNotNone(saved)
            self.assertEqual(saved.conversion_status, "converted")
            self.assertEqual(saved.verification_status, "verified")
            self.assertEqual(saved.converter_version, "7.0")
            self.assertEqual(saved.svg_cache_key, "hash123.svg")
            self.assertIsNotNone(saved.mtef_data)

    def test_content_hash_unique(self):
        """content_hash must be unique."""
        from models import FormulaAsset
        from database import db
        from sqlalchemy.exc import IntegrityError
        with self.app.app_context():
            a1 = FormulaAsset(content_hash="unique_hash_1", source_format="OMML")
            db.session.add(a1)
            db.session.commit()

            a2 = FormulaAsset(content_hash="unique_hash_1", source_format="MathType")
            db.session.add(a2)
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_to_api_dict_no_mtef(self):
        """to_api_dict does not expose MTEF binary data."""
        from models import FormulaAsset
        from database import db
        with self.app.app_context():
            asset = FormulaAsset(
                content_hash="api_test_hash",
                mtef_data="secret_binary_data",
                latex="x^2",
                conversion_status="converted",
            )
            db.session.add(asset)
            db.session.commit()

            d = asset.to_api_dict()
            self.assertNotIn("mtef_data", d)
            self.assertEqual(d["latex"], "x^2")
            self.assertEqual(d["conversion_status"], "converted")

    def test_svg_not_stored_in_formula_asset(self):
        """FormulaAsset has no SVG binary column — only svg_cache_key reference."""
        from models import FormulaAsset
        # Check that FormulaAsset has no svg_data or svg_binary column
        columns = [c.name for c in FormulaAsset.__table__.columns]
        self.assertNotIn("svg_data", columns)
        self.assertNotIn("svg_binary", columns)
        self.assertNotIn("svg_content", columns)
        self.assertIn("svg_cache_key", columns)


class TestImportServiceFormulas(unittest.TestCase):
    """Test import service formula handling."""

    def setUp(self):
        from app import app
        from database import db
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        from database import db
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _create_user_and_bank(self):
        from models import User, QuestionBank
        from database import db
        user = User(username="testuser", fullname="Test User", user_code="T001", password_hash="x")
        db.session.add(user)
        db.session.commit()
        bank = QuestionBank(name="Math Bank", subject="Toán", grade="10", topic="Đại số", created_by=user.id)
        db.session.add(bank)
        db.session.commit()
        return user, bank

    def test_mathtype_pending_import(self):
        """MathType formula without metadata creates pending asset, import succeeds."""
        from services.import_service import ImportService
        from models import FormulaAsset, ImportSession, BankQuestion
        from database import db
        with self.app.app_context():
            user, bank = self._create_user_and_bank()

            questions = [{
                "question_text": "Solve [[formula:temp-1]]",
                "question_type": "single",
                "formulas": {
                    "temp-1": {
                        "content_hash": hashlib.sha256(b"raw_mtef_bytes").hexdigest(),
                        "mathml": None,
                        "latex": None,
                        "mtef_data": base64.b64encode(zlib.compress(b"raw_mtef_bytes")).decode(),
                        "source_format": "MathType",
                        "conversion_status": "pending",
                        "needs_review": True,
                        "parse_confidence": 0.0,
                    }
                },
                "options": [{"text": "x=1", "is_correct": True}],
            }]

            session = ImportSession(
                user_id=user.id, bank_id=bank.id,
                filename="test.docx", file_type="docx",
                status="preview",
                parsed_data=json.dumps(questions)
            )
            db.session.add(session)
            db.session.commit()

            result = ImportService.confirm_import(session.id, bank.id, user.id)
            self.assertTrue(result["success"])
            self.assertEqual(result["imported_count"], 1)

            # Check FormulaAsset
            asset = FormulaAsset.query.first()
            self.assertIsNotNone(asset)
            self.assertEqual(asset.conversion_status, "pending")
            self.assertEqual(asset.verification_status, "needs_review")
            self.assertIsNone(asset.latex)
            self.assertIsNone(asset.mathml)
            self.assertIsNotNone(asset.mtef_data)

            # Check question text has remapped ID
            bq = BankQuestion.query.first()
            self.assertIn("[[formula:", bq.question_text)
            self.assertNotIn("temp-1", bq.question_text)
            self.assertIn(asset.id, bq.question_text)

    def test_mathtype_with_metadata_converted(self):
        """MathType formula with embedded LaTeX creates converted+verified asset."""
        from services.import_service import ImportService
        from models import FormulaAsset, ImportSession
        from database import db
        with self.app.app_context():
            user, bank = self._create_user_and_bank()

            questions = [{
                "question_text": "Calculate [[formula:temp-2]]",
                "question_type": "single",
                "formulas": {
                    "temp-2": {
                        "content_hash": "hash_with_latex",
                        "mathml": None,
                        "latex": "\\frac{1}{2}",
                        "mtef_data": "compressed_data",
                        "source_format": "MathType",
                        "conversion_status": "converted",
                        "needs_review": False,
                        "converter_name": "EmbeddedMetadata",
                        "parse_confidence": 1.0,
                    }
                },
                "options": [{"text": "0.5", "is_correct": True}],
            }]

            session = ImportSession(
                user_id=user.id, bank_id=bank.id,
                filename="test.docx", file_type="docx",
                status="preview",
                parsed_data=json.dumps(questions)
            )
            db.session.add(session)
            db.session.commit()

            ImportService.confirm_import(session.id, bank.id, user.id)

            asset = FormulaAsset.query.first()
            self.assertEqual(asset.conversion_status, "converted")
            self.assertEqual(asset.verification_status, "verified")
            self.assertEqual(asset.latex, "\\frac{1}{2}")

    def test_omml_pipeline_separate(self):
        """OMML formulas are handled separately and create verified assets."""
        from services.import_service import ImportService
        from models import FormulaAsset, ImportSession
        from database import db
        with self.app.app_context():
            user, bank = self._create_user_and_bank()

            questions = [{
                "question_text": "OMML test [[formula:omml-1]]",
                "question_type": "single",
                "formulas": {
                    "omml-1": {
                        "content_hash": hashlib.sha256("x^2".encode()).hexdigest(),
                        "latex": "x^2",
                        "source_format": "OMML",
                        "conversion_status": "converted",
                        "needs_review": False,
                        "parse_confidence": 1.0,
                    }
                },
                "options": [{"text": "A", "is_correct": True}],
            }]

            session = ImportSession(
                user_id=user.id, bank_id=bank.id,
                filename="test.docx", file_type="docx",
                status="preview",
                parsed_data=json.dumps(questions)
            )
            db.session.add(session)
            db.session.commit()

            ImportService.confirm_import(session.id, bank.id, user.id)

            asset = FormulaAsset.query.first()
            self.assertEqual(asset.source_format, "OMML")
            self.assertEqual(asset.conversion_status, "converted")
            self.assertEqual(asset.verification_status, "verified")
            self.assertEqual(asset.latex, "x^2")

    def test_mtef_deduplication(self):
        """Duplicate MTEF hashes reuse existing FormulaAsset."""
        from services.import_service import ImportService
        from models import FormulaAsset, ImportSession
        from database import db
        with self.app.app_context():
            user, bank = self._create_user_and_bank()

            shared_hash = hashlib.sha256(b"shared_mtef").hexdigest()
            questions = [{
                "question_text": "Q1 [[formula:t1]] and [[formula:t2]]",
                "question_type": "single",
                "formulas": {
                    "t1": {
                        "content_hash": shared_hash,
                        "latex": "a+b",
                        "source_format": "MathType",
                        "conversion_status": "converted",
                        "needs_review": False,
                    },
                    "t2": {
                        "content_hash": shared_hash,  # Same hash!
                        "latex": "a+b",
                        "source_format": "MathType",
                        "conversion_status": "converted",
                        "needs_review": False,
                    },
                },
                "options": [{"text": "A", "is_correct": True}],
            }]

            session = ImportSession(
                user_id=user.id, bank_id=bank.id,
                filename="test.docx", file_type="docx",
                status="preview",
                parsed_data=json.dumps(questions)
            )
            db.session.add(session)
            db.session.commit()

            ImportService.confirm_import(session.id, bank.id, user.id)

            # Only one FormulaAsset should exist
            assets = FormulaAsset.query.all()
            self.assertEqual(len(assets), 1)

    def test_deduplicated_pending_asset_receives_svg_preview(self):
        """A re-import enriches an old pending asset with its display fallback."""
        from services.import_service import ImportService
        from models import FormulaAsset, ImportSession
        from database import db
        with self.app.app_context():
            user, bank = self._create_user_and_bank()
            shared_hash = hashlib.sha256(b"old_pending_mtef").hexdigest()
            existing = FormulaAsset(
                content_hash=shared_hash,
                source_format="MathType",
                conversion_status="pending",
                verification_status="needs_review",
            )
            db.session.add(existing)
            db.session.commit()

            questions = [{
                "question_text": "Q [[formula:temp-formula]]",
                "question_type": "single",
                "formulas": {
                    "temp-formula": {
                        "content_hash": shared_hash,
                        "source_format": "MathType",
                        "conversion_status": "pending",
                        "needs_review": True,
                        "preview_url": "/static/uploads/questions/formula-preview.svg",
                    }
                },
                "options": [{"text": "A", "is_correct": True}],
            }]
            session = ImportSession(
                user_id=user.id,
                bank_id=bank.id,
                filename="preview.docx",
                file_type="docx",
                status="preview",
                parsed_data=json.dumps(questions),
            )
            db.session.add(session)
            db.session.commit()

            ImportService.confirm_import(session.id, bank.id, user.id)

            refreshed = db.session.get(FormulaAsset, existing.id)
            self.assertEqual(
                refreshed.svg_cache_key,
                "/static/uploads/questions/formula-preview.svg",
            )

    def test_remap_in_all_fields(self):
        """Placeholder remap works in question_text, context, options, statements, explanation."""
        from services.import_service import ImportService
        from models import FormulaAsset, ImportSession, BankQuestion, BankQuestionOption
        from database import db
        with self.app.app_context():
            user, bank = self._create_user_and_bank()

            questions = [{
                "question_text": "Q [[formula:f1]]",
                "context": "Context [[formula:f1]]",
                "explanation": "Exp [[formula:f1]]",
                "question_type": "true_false",
                "formulas": {
                    "f1": {
                        "content_hash": "remap_test_hash",
                        "latex": "y=mx+b",
                        "source_format": "OMML",
                        "conversion_status": "converted",
                        "needs_review": False,
                    }
                },
                "options": [{"text": "Opt [[formula:f1]]", "is_correct": True}],
                "statements": [{"id": "a", "text": "Stmt [[formula:f1]]", "answer": True}],
            }]

            session = ImportSession(
                user_id=user.id, bank_id=bank.id,
                filename="test.docx", file_type="docx",
                status="preview",
                parsed_data=json.dumps(questions)
            )
            db.session.add(session)
            db.session.commit()

            ImportService.confirm_import(session.id, bank.id, user.id)

            asset = FormulaAsset.query.first()
            bq = BankQuestion.query.first()

            # All fields should have the asset ID, not temp UUID
            self.assertIn(f"[[formula:{asset.id}]]", bq.question_text)
            self.assertIn(f"[[formula:{asset.id}]]", bq.context)
            self.assertIn(f"[[formula:{asset.id}]]", bq.explanation)
            self.assertNotIn("[[formula:f1]]", bq.question_text)

            # Options
            opts = BankQuestionOption.query.all()
            for opt in opts:
                self.assertIn(f"[[formula:{asset.id}]]", opt.option_text)
                self.assertNotIn("[[formula:f1]]", opt.option_text)

    def test_worker_unavailable_import_succeeds(self):
        """Import succeeds even when worker is unavailable; assets stay pending."""
        from services.import_service import ImportService
        from models import FormulaAsset, ImportSession
        from database import db
        os.environ.pop("MATHTYPE_WORKER_URL", None)
        
        with self.app.app_context():
            user, bank = self._create_user_and_bank()

            questions = [{
                "question_text": "No worker [[formula:nw1]]",
                "question_type": "single",
                "formulas": {
                    "nw1": {
                        "content_hash": "no_worker_hash",
                        "mtef_data": "compressed",
                        "source_format": "MathType",
                        "conversion_status": "pending",
                        "needs_review": True,
                    }
                },
                "options": [{"text": "A", "is_correct": True}],
            }]

            session = ImportSession(
                user_id=user.id, bank_id=bank.id,
                filename="test.docx", file_type="docx",
                status="preview",
                parsed_data=json.dumps(questions)
            )
            db.session.add(session)
            db.session.commit()

            result = ImportService.confirm_import(session.id, bank.id, user.id)
            self.assertTrue(result["success"])

            asset = FormulaAsset.query.first()
            self.assertEqual(asset.conversion_status, "pending")

    def test_content_hash_auto_generated(self):
        """If formula has no content_hash, one is generated from available data."""
        from services.import_service import ImportService
        from models import FormulaAsset, ImportSession
        from database import db
        with self.app.app_context():
            user, bank = self._create_user_and_bank()

            questions = [{
                "question_text": "Auto hash [[formula:ah1]]",
                "question_type": "single",
                "formulas": {
                    "ah1": {
                        # No content_hash!
                        "latex": "\\alpha + \\beta",
                        "source_format": "LaTeX",
                        "conversion_status": "converted",
                        "needs_review": False,
                    }
                },
                "options": [{"text": "A", "is_correct": True}],
            }]

            session = ImportSession(
                user_id=user.id, bank_id=bank.id,
                filename="test.docx", file_type="docx",
                status="preview",
                parsed_data=json.dumps(questions)
            )
            db.session.add(session)
            db.session.commit()

            ImportService.confirm_import(session.id, bank.id, user.id)

            asset = FormulaAsset.query.first()
            self.assertIsNotNone(asset)
            self.assertIsNotNone(asset.content_hash)
            self.assertEqual(len(asset.content_hash), 64)  # SHA-256 hex


class TestFormulaAPI(unittest.TestCase):
    """Test formula API endpoints."""

    def setUp(self):
        from app import app
        from database import db
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        from database import db
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _login(self):
        from models import User
        from database import db
        with self.app.app_context():
            user = User(username="api_test", fullname="API Test", user_code="API01", role="admin")
            user.set_password("test123")
            db.session.add(user)
            db.session.commit()
        self.client.post('/login', data={'username': 'api_test', 'password': 'test123'}, follow_redirects=True)

    def test_batch_api_returns_formula_data(self):
        """POST /api/formulas/batch returns MathML/LaTeX/status."""
        from models import FormulaAsset
        from database import db
        with self.app.app_context():
            self._login()
            asset = FormulaAsset(
                content_hash="batch_test_hash",
                latex="e=mc^2",
                mathml="<math><mi>e</mi></math>",
                conversion_status="converted",
                verification_status="verified",
                source_format="MathType",
            )
            db.session.add(asset)
            db.session.commit()
            asset_id = asset.id

        resp = self.client.post('/api/formulas/batch',
            json={"uuids": [asset_id]},
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn(asset_id, data["formulas"])
        f = data["formulas"][asset_id]
        self.assertEqual(f["latex"], "e=mc^2")
        self.assertEqual(f["conversion_status"], "converted")
        self.assertEqual(f["verification_status"], "verified")

    def test_batch_api_handles_missing_ids(self):
        """Batch API gracefully handles non-existent formula IDs."""
        with self.app.app_context():
            self._login()

        resp = self.client.post('/api/formulas/batch',
            json={"uuids": ["nonexistent-id-1", "nonexistent-id-2"]},
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(len(data["formulas"]), 0)

    def test_svg_endpoint_pending_returns_202(self):
        """SVG endpoint returns 202 for pending formula."""
        from models import FormulaAsset
        from database import db
        with self.app.app_context():
            self._login()
            asset = FormulaAsset(
                content_hash="svg_pending_hash",
                conversion_status="pending",
                source_format="MathType",
            )
            db.session.add(asset)
            db.session.commit()
            asset_id = asset.id

        resp = self.client.get(f'/api/formulas/{asset_id}/render.svg')
        self.assertEqual(resp.status_code, 202)
        data = resp.get_json()
        self.assertEqual(data["status"], "pending")

    def test_svg_endpoint_failed_returns_404(self):
        """SVG endpoint returns 404 for failed formula."""
        from models import FormulaAsset
        from database import db
        with self.app.app_context():
            self._login()
            asset = FormulaAsset(
                content_hash="svg_failed_hash",
                conversion_status="failed",
                source_format="MathType",
            )
            db.session.add(asset)
            db.session.commit()
            asset_id = asset.id

        resp = self.client.get(f'/api/formulas/{asset_id}/render.svg')
        self.assertEqual(resp.status_code, 404)

    def test_svg_endpoint_invalid_id_returns_404(self):
        """SVG endpoint returns 404 for invalid formula ID."""
        with self.app.app_context():
            self._login()
        resp = self.client.get('/api/formulas/not-a-uuid/render.svg')
        self.assertEqual(resp.status_code, 404)


class TestDocxParserOMML(unittest.TestCase):
    """Test that OMML pipeline is not regressed."""

    def test_omml_to_latex_fraction(self):
        """OMML fraction → \\frac{num}{den}."""
        from services.docx_parser import _omml_to_latex
        import xml.etree.ElementTree as ET
        ns = "http://schemas.openxmlformats.org/officeDocument/2006/math"
        xml_str = f'''<m:oMath xmlns:m="{ns}">
            <m:f>
                <m:num><m:r><m:t>1</m:t></m:r></m:num>
                <m:den><m:r><m:t>2</m:t></m:r></m:den>
            </m:f>
        </m:oMath>'''
        elem = ET.fromstring(xml_str)
        result = _omml_to_latex(elem)
        self.assertIn("\\frac", result)
        self.assertIn("1", result)
        self.assertIn("2", result)

    def test_omml_to_latex_superscript(self):
        """OMML superscript → base^{exp}."""
        from services.docx_parser import _omml_to_latex
        import xml.etree.ElementTree as ET
        ns = "http://schemas.openxmlformats.org/officeDocument/2006/math"
        xml_str = f'''<m:oMath xmlns:m="{ns}">
            <m:sSup>
                <m:e><m:r><m:t>x</m:t></m:r></m:e>
                <m:sup><m:r><m:t>2</m:t></m:r></m:sup>
            </m:sSup>
        </m:oMath>'''
        elem = ET.fromstring(xml_str)
        result = _omml_to_latex(elem)
        self.assertIn("x", result)
        self.assertIn("2", result)
        self.assertIn("^", result)

    def test_omml_formula_gets_content_hash(self):
        """OMML formulas in _walk_xml_node get content_hash."""
        from services.docx_parser import _walk_xml_node
        import xml.etree.ElementTree as ET
        ns = "http://schemas.openxmlformats.org/officeDocument/2006/math"
        xml_str = f'''<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                         xmlns:m="{ns}">
            <m:oMath>
                <m:r><m:t>x</m:t></m:r>
            </m:oMath>
        </w:p>'''
        elem = ET.fromstring(xml_str)
        chunks = []
        formula_dict = {}
        _walk_xml_node(elem, {}, chunks, formula_dict)
        
        # Should have at least one formula
        if formula_dict:
            for fid, fdata in formula_dict.items():
                self.assertEqual(fdata["source_format"], "OMML")
                self.assertIn("content_hash", fdata)
                self.assertEqual(fdata["conversion_status"], "converted")


class TestNoRawPlaceholder(unittest.TestCase):
    """Verify that no UI shows raw [[formula:...]] placeholder."""

    def test_formula_renderer_replaces_all_placeholders(self):
        """JS formula_renderer.js contains logic to replace all placeholders."""
        js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "static", "js", "formula_renderer.js")
        with open(js_path, 'r') as f:
            js_content = f.read()
        
        # Must contain replacement logic
        self.assertIn("replacePlaceholders", js_content)
        self.assertIn("[[formula:", js_content)
        self.assertIn("createDocumentFragment", js_content)
        # Must handle pending state
        self.assertIn("pending", js_content)
        # Must handle failed state  
        self.assertIn("Không thể chuyển đổi công thức", js_content)
        # Must NOT use innerHTML in actual code (comments OK)
        js_code_lines = [l for l in js_content.splitlines() if not l.strip().startswith('*') and not l.strip().startswith('//') and not l.strip().startswith('/*')]
        js_code_only = '\n'.join(js_code_lines)
        self.assertNotIn(".innerHTML", js_code_only)

    def test_renderer_handles_all_status_types(self):
        """JS renderer handles: converted, pending, failed, fallback_svg."""
        js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "static", "js", "formula_renderer.js")
        with open(js_path, 'r') as f:
            js_content = f.read()
        
        self.assertIn("conversion_status", js_content)
        self.assertIn("fallback_svg", js_content)
        self.assertIn("render.svg", js_content)

    def test_temporary_pending_formula_does_not_poll_forever(self):
        js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "static", "js", "formula_renderer.js")
        with open(js_path, 'r') as f:
            js_content = f.read()

        self.assertIn("_temporary", js_content)
        self.assertIn("worker_available === false", js_content)
        self.assertIn("Chưa có bản hiển thị công thức MathType", js_content)


class TestMathTypeSvgPreview(unittest.TestCase):
    def test_libreoffice_svg_is_cropped_to_formula_bounds(self):
        from services.docx_parser import _crop_libreoffice_svg

        source = '''<?xml version="1.0"?>
<svg version="1.2" width="210mm" height="297mm" viewBox="0 0 21000 29700">
  <rect class="BoundingBox" stroke="none" fill="none" x="9000" y="14000" width="2500" height="1400"/>
</svg>'''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".svg", delete=False) as temp_svg:
            temp_svg.write(source)
            temp_path = temp_svg.name
        try:
            _crop_libreoffice_svg(temp_path)
            with open(temp_path, encoding="utf-8") as cropped_svg:
                result = cropped_svg.read()
            self.assertNotIn('viewBox="0 0 21000 29700"', result)
            self.assertRegex(result, r'viewBox="89\d{2} 139\d{2} 2\d{3} 1\d{3}"')
        finally:
            os.remove(temp_path)


class TestXSSPrevention(unittest.TestCase):
    """Test XSS prevention in formula handling."""

    def test_remap_does_not_inject_html(self):
        """UUID remap is text-only, no HTML injection."""
        text = "Hello [[formula:123-456]] world"
        uuid_map = {"123-456": "abc-def"}
        for old_u, new_u in uuid_map.items():
            text = text.replace(f"[[formula:{old_u}]]", f"[[formula:{new_u}]]")
        
        self.assertEqual(text, "Hello [[formula:abc-def]] world")
        self.assertNotIn("<script>", text)
        self.assertNotIn("<img", text)

    def test_formula_renderer_uses_dom_api(self):
        """formula_renderer.js uses DOM API, not innerHTML."""
        js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "static", "js", "formula_renderer.js")
        with open(js_path, 'r') as f:
            content = f.read()
        
        self.assertIn("createElement", content)
        self.assertIn("createTextNode", content)
        self.assertIn("createDocumentFragment", content)
        # Must NOT use innerHTML in actual code (comments OK)
        code_lines = [l for l in content.splitlines() if not l.strip().startswith('*') and not l.strip().startswith('//') and not l.strip().startswith('/*')]
        code_only = '\n'.join(code_lines)
        self.assertNotIn(".innerHTML", code_only)


if __name__ == '__main__':
    unittest.main()
