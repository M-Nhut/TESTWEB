"""
MathType SDK Conversion Worker — Windows service for MTEF → MathML/LaTeX/SVG conversion.

This is designed to run on a Windows machine with MathType SDK installed and licensed.
It provides a REST API that the Flask app calls to convert MTEF binary data.

Requirements:
  - Windows OS
  - MathType SDK installed and activated with a valid license
  - Python 3.8+ with Flask, comtypes (for COM automation)
  
Environment Variables:
  - MATHTYPE_WORKER_TOKEN: Bearer token for request authentication
  - MATHTYPE_WORKER_PORT: Port to listen on (default: 8081)
  - MATHTYPE_SVG_CACHE_DIR: Directory for SVG cache (default: ./svg_cache)
  - MATHTYPE_SVG_CACHE_TTL: TTL in seconds for cached SVGs (default: 86400 = 24h)

Usage:
  python worker.py
"""

import base64
import hashlib
import json
import os
import sys
import time
import zlib
import logging
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Configuration
# ---------------------------------------------------------------------------

WORKER_TOKEN = os.environ.get("MATHTYPE_WORKER_TOKEN", "")
WORKER_PORT = int(os.environ.get("MATHTYPE_WORKER_PORT", "8081"))
SVG_CACHE_DIR = os.environ.get("MATHTYPE_SVG_CACHE_DIR", "./svg_cache")
SVG_CACHE_TTL = int(os.environ.get("MATHTYPE_SVG_CACHE_TTL", "86400"))  # 24h default

# Cache for conversion results (in-memory, keyed by SHA-256 hash)
_conversion_cache = {}

# ---------------------------------------------------------------------------
#  MathType SDK Adapter (COM/SDK interface)
# ---------------------------------------------------------------------------

class MathTypeSDKAdapter:
    """
    Adapter for MathType SDK COM automation.
    
    This class must be implemented based on the specific MathType SDK version
    installed on the system. The interface methods are defined here as a contract.
    
    To implement:
    1. Install MathType SDK on Windows
    2. Activate with a valid license  
    3. Use comtypes or win32com to automate MTEF → MathML/LaTeX conversion
    
    Example implementation sketch:
        import comtypes.client
        mt = comtypes.client.CreateObject("MT6.Application")
        # ... use SDK methods to convert MTEF
    """
    
    def __init__(self):
        self._sdk = None
        self._sdk_version = "not_initialized"
        self._initialized = False
    
    def initialize(self):
        """
        Initialize MathType SDK COM object.
        Must be called on the main thread (COM apartment).
        """
        try:
            # Attempt to load MathType SDK via COM
            # This will only work on Windows with MathType SDK installed
            import comtypes.client
            self._sdk = comtypes.client.CreateObject("MathTypeSDK.Application")
            self._sdk_version = str(getattr(self._sdk, 'Version', 'unknown'))
            self._initialized = True
            logger.info(f"MathType SDK initialized: version {self._sdk_version}")
        except ImportError:
            logger.warning("comtypes not installed. MathType SDK not available.")
            self._initialized = False
        except Exception as e:
            logger.warning(f"MathType SDK initialization failed: {e}")
            logger.warning("Ensure MathType SDK is installed and licensed on this Windows machine.")
            self._initialized = False
    
    @property
    def is_available(self):
        return self._initialized and self._sdk is not None
    
    @property
    def version(self):
        return self._sdk_version
    
    def convert_mtef_to_mathml(self, mtef_bytes):
        """
        Convert raw MTEF bytes to MathML string.
        
        Returns:
            str or None: MathML string, or None if conversion fails.
        """
        if not self.is_available:
            return None
        
        try:
            # SDK-specific conversion logic
            # This is a placeholder — actual implementation depends on SDK API
            # result = self._sdk.ConvertToMathML(mtef_bytes)
            # return result
            raise NotImplementedError("MathType SDK conversion not implemented — install and configure SDK")
        except Exception as e:
            logger.error(f"MTEF→MathML conversion error: {e}")
            return None
    
    def convert_mtef_to_latex(self, mtef_bytes):
        """
        Convert raw MTEF bytes to LaTeX string.
        
        Returns:
            str or None: LaTeX string, or None if conversion fails.
        """
        if not self.is_available:
            return None
        
        try:
            raise NotImplementedError("MathType SDK conversion not implemented — install and configure SDK")
        except Exception as e:
            logger.error(f"MTEF→LaTeX conversion error: {e}")
            return None
    
    def render_mtef_to_svg(self, mtef_bytes):
        """
        Render MTEF as SVG vector image.
        
        Returns:
            bytes or None: SVG content, or None if rendering fails.
        """
        if not self.is_available:
            return None
        
        try:
            raise NotImplementedError("MathType SDK SVG rendering not implemented — install and configure SDK")
        except Exception as e:
            logger.error(f"MTEF→SVG rendering error: {e}")
            return None


# ---------------------------------------------------------------------------
#  SVG Cache Management
# ---------------------------------------------------------------------------

def _ensure_svg_cache_dir():
    """Ensure SVG cache directory exists."""
    os.makedirs(SVG_CACHE_DIR, exist_ok=True)


def _get_cached_svg(formula_hash):
    """Get cached SVG file by formula hash. Returns bytes or None."""
    cache_path = os.path.join(SVG_CACHE_DIR, f"{formula_hash}.svg")
    if os.path.exists(cache_path):
        # Check TTL
        mtime = os.path.getmtime(cache_path)
        if time.time() - mtime < SVG_CACHE_TTL:
            with open(cache_path, 'rb') as f:
                return f.read()
        else:
            # Expired
            try:
                os.remove(cache_path)
            except OSError:
                pass
    return None


def _cache_svg(formula_hash, svg_content):
    """Cache SVG content to filesystem."""
    _ensure_svg_cache_dir()
    cache_path = os.path.join(SVG_CACHE_DIR, f"{formula_hash}.svg")
    with open(cache_path, 'wb') as f:
        f.write(svg_content if isinstance(svg_content, bytes) else svg_content.encode('utf-8'))


def _cleanup_expired_svgs():
    """Remove expired SVG cache files."""
    try:
        _ensure_svg_cache_dir()
        now = time.time()
        for fname in os.listdir(SVG_CACHE_DIR):
            if fname.endswith('.svg'):
                fpath = os.path.join(SVG_CACHE_DIR, fname)
                if now - os.path.getmtime(fpath) > SVG_CACHE_TTL:
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass
    except Exception as e:
        logger.warning(f"SVG cache cleanup error: {e}")


# ---------------------------------------------------------------------------
#  Flask Worker Application
# ---------------------------------------------------------------------------

def create_worker_app():
    """Create and configure the Flask worker application."""
    from flask import Flask, request, jsonify, Response, abort
    
    app = Flask(__name__)
    sdk_adapter = MathTypeSDKAdapter()
    
    # Try to initialize SDK on startup
    try:
        sdk_adapter.initialize()
    except Exception as e:
        logger.warning(f"SDK initialization deferred: {e}")
    
    def _verify_token():
        """Verify Bearer token from request."""
        if not WORKER_TOKEN:
            return True  # No token configured = no auth required (dev mode)
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:] == WORKER_TOKEN
        return False
    
    @app.before_request
    def check_auth():
        if not _verify_token():
            abort(401)
    
    @app.route('/health', methods=['GET'])
    def health():
        return jsonify({
            'status': 'ok',
            'sdk_available': sdk_adapter.is_available,
            'sdk_version': sdk_adapter.version,
            'cache_dir': SVG_CACHE_DIR,
        })
    
    @app.route('/api/convert', methods=['POST'])
    def convert():
        """
        Convert MTEF to MathML/LaTeX.
        
        Request body:
          {
            "mtef_base64": "<zlib-compressed base64 MTEF>",
            "formula_hash": "<SHA-256 hash>"
          }
        
        Response:
          {
            "mathml": "<MathML string>",
            "latex": "<LaTeX string>",
            "svg_url": "/api/render-svg?hash=<formula_hash>",
            "converter_name": "MathTypeSDK",
            "converter_version": "<version>",
            "confidence": 1.0
          }
        """
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON body'}), 400
        
        mtef_b64 = data.get('mtef_base64')
        formula_hash = data.get('formula_hash')
        
        if not mtef_b64 or not formula_hash:
            return jsonify({'error': 'Missing mtef_base64 or formula_hash'}), 400
        
        # Check cache (idempotency)
        if formula_hash in _conversion_cache:
            cached = _conversion_cache[formula_hash]
            return jsonify(cached), 200
        
        # Decompress MTEF
        try:
            mtef_bytes = zlib.decompress(base64.b64decode(mtef_b64))
        except Exception as e:
            return jsonify({'error': f'Failed to decompress MTEF: {e}'}), 400
        
        if not sdk_adapter.is_available:
            return jsonify({'error': 'MathType SDK not available'}), 503
        
        # Convert
        mathml = sdk_adapter.convert_mtef_to_mathml(mtef_bytes)
        latex = sdk_adapter.convert_mtef_to_latex(mtef_bytes)
        
        # Render SVG
        svg_url = None
        svg_content = sdk_adapter.render_mtef_to_svg(mtef_bytes)
        if svg_content:
            _cache_svg(formula_hash, svg_content)
            svg_url = f"/api/render-svg?hash={formula_hash}"
        
        result = {
            'mathml': mathml,
            'latex': latex,
            'svg_url': svg_url,
            'converter_name': 'MathTypeSDK',
            'converter_version': sdk_adapter.version,
            'confidence': 1.0 if (mathml or latex) else 0.0,
        }
        
        # Cache result
        _conversion_cache[formula_hash] = result
        
        return jsonify(result), 200
    
    @app.route('/api/render-svg', methods=['GET', 'POST'])
    def render_svg():
        """
        Render or retrieve cached SVG for a formula.
        
        GET /api/render-svg?hash=<formula_hash>
        POST with {"mtef_base64": "...", "formula_hash": "..."}
        
        Returns SVG with Content-Type: image/svg+xml
        """
        if request.method == 'GET':
            formula_hash = request.args.get('hash')
            if not formula_hash:
                return jsonify({'error': 'Missing hash parameter'}), 400
            
            # Check cache
            svg_content = _get_cached_svg(formula_hash)
            if svg_content:
                return Response(svg_content, mimetype='image/svg+xml',
                              headers={'Cache-Control': 'public, max-age=86400'})
            
            return jsonify({'error': 'SVG not cached'}), 404
        
        # POST: render SVG from MTEF
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON body'}), 400
        
        mtef_b64 = data.get('mtef_base64')
        formula_hash = data.get('formula_hash')
        
        if not mtef_b64 or not formula_hash:
            return jsonify({'error': 'Missing mtef_base64 or formula_hash'}), 400
        
        # Check cache first
        svg_content = _get_cached_svg(formula_hash)
        if svg_content:
            return Response(svg_content, mimetype='image/svg+xml',
                          headers={'Cache-Control': 'public, max-age=86400'})
        
        # Decompress and render
        try:
            mtef_bytes = zlib.decompress(base64.b64decode(mtef_b64))
        except Exception as e:
            return jsonify({'error': f'Failed to decompress MTEF: {e}'}), 400
        
        if not sdk_adapter.is_available:
            return jsonify({'error': 'MathType SDK not available'}), 503
        
        svg_content = sdk_adapter.render_mtef_to_svg(mtef_bytes)
        if svg_content:
            _cache_svg(formula_hash, svg_content)
            return Response(svg_content, mimetype='image/svg+xml',
                          headers={'Cache-Control': 'public, max-age=86400'})
        
        return jsonify({'error': 'SVG rendering failed'}), 500
    
    return app


# ---------------------------------------------------------------------------
#  Entry Point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if not WORKER_TOKEN:
        logger.warning("⚠️  MATHTYPE_WORKER_TOKEN not set — running without authentication (dev mode)")
    
    _ensure_svg_cache_dir()
    _cleanup_expired_svgs()
    
    app = create_worker_app()
    logger.info(f"Starting MathType Worker on port {WORKER_PORT}")
    app.run(host='0.0.0.0', port=WORKER_PORT, debug=False)
