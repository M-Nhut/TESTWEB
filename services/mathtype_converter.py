"""
MathType Conversion Service — Production-grade MTEF extraction and conversion pipeline.

Architecture:
  1. extract_raw_mtef(): Locates DSMT header in WMF/OLE bytes, extracts raw MTEF payload.
  2. EmbeddedMetadataProvider: Extracts TeX/MathML metadata embedded by MathType application
     translators. Only uses metadata genuinely present in the binary — no heuristic conversion.
  3. MathTypeWorkerClient: Calls external Windows MathType SDK worker for genuine MTEF→MathML/LaTeX
     conversion. URL and token from environment variables. Retry + timeout + idempotency by hash.
  4. process_mathtype_formula(): Top-level entry point used by docx_parser.
     - Extracts raw MTEF and computes SHA-256 on raw bytes BEFORE compression.
     - Checks embedded metadata first (genuine TeX/MathML from MathType translators).
     - If no metadata, returns MTEF data as pending for worker conversion.
     - Never produces heuristic LaTeX as verified output.
"""

import base64
import hashlib
import os
import time
import zlib
import logging
from io import BytesIO

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Raw MTEF Extraction
# ---------------------------------------------------------------------------

# DSMT header versions to search for, in order of preference
_DSMT_HEADERS = [
    (b"DSMT7\x00", 7),
    (b"DSMT6\x00", 6),
    (b"DSMT5\x00", 5),
    (b"DSMT4\x00", 4),
    (b"DSMT3\x00", 3),
    (b"DSMT2\x00", 2),
    (b"DSMT\x00", 1),
    (b"DSMT", 0),
]


def _binary_variants(data):
    """Yield the original binary and streams inside an OLE compound file.

    Word stores MathType as an OLE compound document in many DOCX files. In
    that form the MTEF is commonly in ``Equation Native`` rather than in the
    outer ``oleObject*.bin`` bytes. ``olefile`` is optional so ordinary WMF
    imports keep working even in minimal deployments.
    """
    if not data:
        return
    yield data
    try:
        import olefile
        if not olefile.isOleFile(data):
            return
        with olefile.OleFileIO(BytesIO(data)) as ole:
            for stream_name in ole.listdir(streams=True, storages=False):
                try:
                    stream = ole.openstream(stream_name).read()
                except Exception:
                    continue
                if stream:
                    yield stream
    except (ImportError, OSError, ValueError):
        return
    except Exception as exc:
        logger.debug("Unable to inspect OLE streams: %s", exc)


def extract_raw_mtef(wmf_bytes):
    """
    Extract raw MTEF payload bytes from WMF/EMF/OLE binary.

    Returns:
        tuple: (raw_mtef_bytes, dsmt_version) or (None, None) if not found.
    """
    if not wmf_bytes:
        return None, None

    for binary in _binary_variants(wmf_bytes):
        for header, version in _DSMT_HEADERS:
            idx = binary.find(header)
            if idx >= 0:
                # Payload starts after the header
                payload_start = idx + len(header)
                raw_mtef = binary[payload_start:]
                return raw_mtef, version

    return None, None


def compute_mtef_hash(raw_mtef_bytes):
    """
    Compute SHA-256 hash on raw MTEF bytes BEFORE any compression.
    This is the canonical content_hash for deduplication.
    """
    if not raw_mtef_bytes:
        return None
    return hashlib.sha256(raw_mtef_bytes).hexdigest()


def compress_mtef(raw_mtef_bytes):
    """
    Compress raw MTEF with zlib and encode as base64.
    Used for storage in FormulaAsset.mtef_data.
    """
    if not raw_mtef_bytes:
        return None
    return base64.b64encode(zlib.compress(raw_mtef_bytes, level=6)).decode('ascii')


# ---------------------------------------------------------------------------
#  Embedded Metadata Provider
# ---------------------------------------------------------------------------

class EmbeddedMetadataProvider:
    """
    Extracts genuine TeX or MathML metadata embedded in MathType binary
    by MathType's application translators. Does NOT perform heuristic conversion.
    """

    def extract_metadata(self, wmf_bytes):
        """
        Search for embedded TeX Input Language or MathML metadata.

        Returns:
            dict: {mathml, latex, confidence, provider_name, error}
        """
        result = {
            "mathml": None,
            "latex": None,
            "confidence": 0.0,
            "provider_name": "EmbeddedMetadataProvider",
            "error": None,
        }

        if not wmf_bytes:
            result["error"] = "No WMF bytes provided"
            return result

        for binary in _binary_variants(wmf_bytes):
            # Try to find embedded TeX string from MathType translator data
            tex_idx = binary.find(b"TeX Input Language")
            if tex_idx >= 0:
                null_after_tex = binary.find(b"\x00", tex_idx)
                if null_after_tex >= 0:
                    tex_str_start = null_after_tex + 1
                    tex_str_end = binary.find(b"\x00", tex_str_start)
                    if tex_str_end >= 0 and tex_str_end > tex_str_start:
                        tex_bytes = binary[tex_str_start:tex_str_end]
                        if b"\\" in tex_bytes or b"_" in tex_bytes or b"^" in tex_bytes or b"=" in tex_bytes:
                            try:
                                clean_tex = tex_bytes.decode("utf-8", errors="ignore").strip()
                                if clean_tex.startswith("{") and clean_tex.endswith("}"):
                                    clean_tex = clean_tex[1:-1].strip()
                                clean_tex = clean_tex.replace("\r", " ").replace("\n", " ").strip()
                                clean_tex = clean_tex.replace(r"\begin{align}", r"\begin{aligned}").replace(r"\end{align}", r"\end{aligned}")
                                if clean_tex.startswith("$") and clean_tex.endswith("$"):
                                    clean_tex = clean_tex[1:-1]
                                if clean_tex:
                                    result["latex"] = clean_tex
                                    result["confidence"] = 1.0
                                    return result
                            except Exception:
                                pass

            # Try MathML metadata
            mathml_idx = binary.find(b"MathML")
            if mathml_idx >= 0:
                null_after = binary.find(b"\x00", mathml_idx)
                if null_after >= 0:
                    mml_start = null_after + 1
                    mml_end = binary.find(b"\x00", mml_start)
                    if mml_end >= 0 and mml_end > mml_start:
                        try:
                            mml_str = binary[mml_start:mml_end].decode("utf-8", errors="ignore").strip()
                            if mml_str.startswith("<math"):
                                result["mathml"] = mml_str
                                result["confidence"] = 1.0
                                return result
                        except Exception:
                            pass

        return result


# ---------------------------------------------------------------------------
#  MathType Worker Client
# ---------------------------------------------------------------------------

class MathTypeWorkerClient:
    """
    Client for the external MathType SDK conversion worker (Windows service).

    Configuration via environment variables:
      - MATHTYPE_WORKER_URL: Base URL of the worker (e.g., http://192.168.1.100:8081)
      - MATHTYPE_WORKER_TOKEN: Bearer token for authentication

    Features:
      - Retry with exponential backoff (max 3 attempts)
      - Configurable timeout
      - Idempotency via formula_hash
    """

    MAX_RETRIES = 3
    BASE_TIMEOUT = 10  # seconds
    RETRY_BACKOFF = 2  # exponential base

    def __init__(self):
        self.worker_url = os.environ.get("MATHTYPE_WORKER_URL", "").rstrip("/")
        self.worker_token = os.environ.get("MATHTYPE_WORKER_TOKEN", "")

    @property
    def is_available(self):
        """Check if worker URL is configured."""
        return bool(self.worker_url)

    def convert(self, mtef_base64_compressed, formula_hash):
        """
        Send MTEF to worker for conversion.

        Args:
            mtef_base64_compressed: zlib-compressed, base64-encoded MTEF data
            formula_hash: SHA-256 hash for idempotency

        Returns:
            dict: {mathml, latex, svg_url, status, converter_name, converter_version, error}
        """
        if not self.is_available:
            return self._unavailable_result("Worker URL not configured")

        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                import requests
                headers = {
                    "Content-Type": "application/json",
                }
                if self.worker_token:
                    headers["Authorization"] = f"Bearer {self.worker_token}"

                payload = {
                    "mtef_base64": mtef_base64_compressed,
                    "formula_hash": formula_hash,
                }

                timeout = self.BASE_TIMEOUT * (attempt + 1)
                resp = requests.post(
                    f"{self.worker_url}/api/convert",
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "mathml": data.get("mathml"),
                        "latex": data.get("latex"),
                        "svg_url": data.get("svg_url"),
                        "status": "converted",
                        "converter_name": data.get("converter_name", "MathTypeSDK"),
                        "converter_version": data.get("converter_version", "unknown"),
                        "error": None,
                    }
                elif resp.status_code == 409:
                    # Already processed (idempotent), retrieve cached result
                    data = resp.json()
                    return {
                        "mathml": data.get("mathml"),
                        "latex": data.get("latex"),
                        "svg_url": data.get("svg_url"),
                        "status": "converted",
                        "converter_name": data.get("converter_name", "MathTypeSDK"),
                        "converter_version": data.get("converter_version", "unknown"),
                        "error": None,
                    }
                else:
                    last_error = f"Worker returned status {resp.status_code}"

            except ImportError:
                return self._unavailable_result("requests library not installed")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"MathType worker attempt {attempt + 1} failed: {e}")

            # Exponential backoff
            if attempt < self.MAX_RETRIES - 1:
                time.sleep(self.RETRY_BACKOFF ** attempt)

        return self._unavailable_result(f"Worker failed after {self.MAX_RETRIES} attempts: {last_error}")

    def render_svg(self, mtef_base64_compressed, formula_hash):
        """
        Request SVG rendering from worker.

        Returns:
            dict: {svg_content, svg_cache_key, content_type, error}
        """
        if not self.is_available:
            return {"svg_content": None, "svg_cache_key": None, "content_type": None, "error": "Worker not configured"}

        try:
            import requests
            headers = {"Content-Type": "application/json"}
            if self.worker_token:
                headers["Authorization"] = f"Bearer {self.worker_token}"

            resp = requests.post(
                f"{self.worker_url}/api/render-svg",
                json={"mtef_base64": mtef_base64_compressed, "formula_hash": formula_hash},
                headers=headers,
                timeout=self.BASE_TIMEOUT,
            )

            if resp.status_code == 200:
                content_type = resp.headers.get("Content-Type", "")
                if "image/svg+xml" in content_type:
                    return {
                        "svg_content": resp.content,
                        "svg_cache_key": formula_hash,
                        "content_type": "image/svg+xml",
                        "error": None,
                    }
                else:
                    data = resp.json()
                    return {
                        "svg_content": None,
                        "svg_cache_key": data.get("svg_cache_key"),
                        "content_type": None,
                        "error": None,
                    }
        except Exception as e:
            logger.warning(f"SVG render request failed: {e}")

        return {"svg_content": None, "svg_cache_key": None, "content_type": None, "error": "SVG render failed"}

    @staticmethod
    def _unavailable_result(error_msg):
        return {
            "mathml": None,
            "latex": None,
            "svg_url": None,
            "status": "pending",
            "converter_name": None,
            "converter_version": None,
            "error": error_msg,
        }


# ---------------------------------------------------------------------------
#  Legacy compatibility function (used by docx_parser)
# ---------------------------------------------------------------------------

def extract_mathtype_mtef(wmf_bytes):
    """
    Legacy compatibility: extract and compress MTEF from WMF/OLE bytes.
    Returns base64-encoded zlib-compressed data.

    DEPRECATED: Use extract_raw_mtef + compress_mtef instead for proper hashing.
    """
    if not wmf_bytes:
        return ""
    try:
        raw_mtef, _version = extract_raw_mtef(wmf_bytes)
        if raw_mtef:
            return compress_mtef(raw_mtef)
        # Fallback: compress whole bytes if no DSMT header found
        return base64.b64encode(zlib.compress(wmf_bytes)).decode('ascii')
    except Exception:
        return ""


def process_mathtype_formula(wmf_bytes):
    """
    Top-level entry point for processing a MathType formula from WMF/EMF/OLE bytes.

    Pipeline:
      1. Extract raw MTEF and compute SHA-256 on raw bytes (before compression).
      2. Check for embedded TeX/MathML metadata (genuine translator output).
      3. If metadata found → return with confidence 1.0 (verified).
      4. If no metadata → return as pending with MTEF data for worker conversion.
      5. Never produce heuristic LaTeX as verified output.

    Returns:
        dict with keys: latex, mathml, mtef_base64, content_hash, confidence,
                        provider_name, conversion_status, needs_review, error
    """
    result = {
        "latex": None,
        "mathml": None,
        "mtef_base64": None,
        "content_hash": None,
        "confidence": 0.0,
        "provider_name": None,
        "conversion_status": "pending",
        "needs_review": True,
        "error": None,
    }

    if not wmf_bytes:
        result["error"] = "No binary data provided"
        return result

    # Step 1: Extract raw MTEF
    raw_mtef, dsmt_version = extract_raw_mtef(wmf_bytes)
    if raw_mtef:
        # Hash on raw bytes BEFORE compression
        result["content_hash"] = compute_mtef_hash(raw_mtef)
        result["mtef_base64"] = compress_mtef(raw_mtef)
    else:
        # No DSMT header: hash/compress entire binary as fallback
        result["content_hash"] = hashlib.sha256(wmf_bytes).hexdigest()
        result["mtef_base64"] = base64.b64encode(zlib.compress(wmf_bytes)).decode('ascii')

    # Step 2: Check for embedded metadata (genuine MathType translator output)
    embedded = EmbeddedMetadataProvider().extract_metadata(wmf_bytes)
    if embedded.get("latex") or embedded.get("mathml"):
        result["latex"] = embedded.get("latex")
        result["mathml"] = embedded.get("mathml")
        result["confidence"] = embedded.get("confidence", 1.0)
        result["provider_name"] = "EmbeddedMetadata"
        result["conversion_status"] = "converted"
        result["needs_review"] = False
        return result

    # Step 3: No metadata → asset stays pending for worker conversion
    result["provider_name"] = None
    result["conversion_status"] = "pending"
    result["needs_review"] = True
    return result
