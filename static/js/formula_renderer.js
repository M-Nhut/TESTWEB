/**
 * formula_renderer.js
 * Production-grade formula rendering with MathJax fallback chain.
 *
 * For each [[formula:<id>]] placeholder:
 *   1. Fetch FormulaAsset data via POST /api/formulas/batch
 *   2. If MathML available → MathJax.mathml2chtml (priority)
 *   3. If MathML fails but LaTeX available → MathJax.tex2chtml (fallback 1)
 *   4. If both fail or status=fallback_svg → load SVG from /api/formulas/<id>/render.svg (fallback 2)
 *   5. If conversion pending → show spinner "Đang chuyển đổi công thức…" with polling
 *   6. If failed → show friendly "[Không thể chuyển đổi công thức]"
 *
 * Security:
 *   - All DOM manipulation via DOM API (createElement, createTextNode, etc.)
 *   - No innerHTML, no Jinja |safe for full text
 *   - SVG via sanitized <img> tag (not inline SVG injection)
 */

window.FormulaRenderer = (function() {
    'use strict';

    // Polling interval for pending formulas (ms)
    const PENDING_POLL_INTERVAL = 5000;
    const PENDING_MAX_RETRIES = 60;  // 5 minutes max

    // Track pending formula polls to avoid duplicates
    const _pendingPolls = new Map();

    /**
     * Main entry: scan rootElement for [[formula:<id>]] placeholders and render them.
     * @param {HTMLElement} rootElement - DOM element to scan (default: document.body)
     * @param {Object} temporaryFormulaMap - Pre-loaded formula data (from import preview)
     */
    function renderFormulas(rootElement, temporaryFormulaMap) {
        if (!rootElement) rootElement = document.body;
        temporaryFormulaMap = temporaryFormulaMap || {};

        // 1. Tell MathJax to typeset standard LaTeX on the new elements
        if (window.MathJax && window.MathJax.typesetPromise) {
            window.MathJax.typesetPromise([rootElement]).catch(function(err) {
                console.log('[FormulaRenderer] MathJax typeset:', err.message);
            });
        }

        // 2. Find all text nodes containing [[formula:<uuid>]]
        var walker = document.createTreeWalker(
            rootElement,
            NodeFilter.SHOW_TEXT,
            {
                acceptNode: function(node) {
                    if (node.parentElement && (
                        node.parentElement.tagName === 'SCRIPT' ||
                        node.parentElement.tagName === 'STYLE' ||
                        node.parentElement.tagName === 'TEXTAREA'
                    )) {
                        return NodeFilter.FILTER_REJECT;
                    }
                    if (node.nodeValue && node.nodeValue.indexOf('[[formula:') !== -1) {
                        return NodeFilter.FILTER_ACCEPT;
                    }
                    return NodeFilter.FILTER_SKIP;
                }
            }
        );

        var textNodes = [];
        var uuidSet = new Set();
        var regex = /\[\[formula:([0-9a-fA-F-]+)\]\]/g;

        var node;
        while ((node = walker.nextNode())) {
            textNodes.push(node);
            var match;
            while ((match = regex.exec(node.nodeValue)) !== null) {
                uuidSet.add(match[1]);
            }
        }

        if (uuidSet.size === 0) return;

        var uuidsToFetch = [];
        var finalFormulasMap = {};
        // Copy temporaryFormulaMap
        for (var key in temporaryFormulaMap) {
            if (temporaryFormulaMap.hasOwnProperty(key)) {
                finalFormulasMap[key] = Object.assign({}, temporaryFormulaMap[key], {
                    _temporary: true
                });
            }
        }

        uuidSet.forEach(function(uid) {
            if (!finalFormulasMap[uid]) {
                uuidsToFetch.push(uid);
            }
        });

        var csrfTokenMeta = document.querySelector('meta[name="csrf-token"]');
        var csrfToken = csrfTokenMeta ? csrfTokenMeta.getAttribute('content') : '';

        function proceedToRender() {
            if (window.MathJax && window.MathJax.startup && window.MathJax.startup.promise) {
                window.MathJax.startup.promise.then(function() {
                    _replacePlaceholders(textNodes, finalFormulasMap);
                });
            } else {
                _replacePlaceholders(textNodes, finalFormulasMap);
            }
        }

        if (uuidsToFetch.length > 0) {
            // 3. Fetch missing formula data
            fetch('/api/formulas/batch', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ uuids: uuidsToFetch })
            })
            .then(function(response) { return response.json(); })
            .then(function(data) {
                if (data.success && data.formulas) {
                    for (var fid in data.formulas) {
                        if (data.formulas.hasOwnProperty(fid)) {
                            finalFormulasMap[fid] = data.formulas[fid];
                        }
                    }
                }
                proceedToRender();
            })
            .catch(function(err) {
                console.error('[FormulaRenderer] Fetch error:', err);
                proceedToRender();
            });
        } else {
            proceedToRender();
        }
    }

    /**
     * Replace [[formula:<uuid>]] text nodes with rendered math elements.
     */
    function _replacePlaceholders(nodes, formulasMap) {
        nodes.forEach(function(textNode) {
            var parent = textNode.parentNode;
            if (!parent) return;

            var parts = textNode.nodeValue.split(/(\[\[formula:[0-9a-fA-F-]+\]\])/);
            if (parts.length <= 1) return;

            var fragment = document.createDocumentFragment();

            parts.forEach(function(part) {
                var match = part.match(/^\[\[formula:([0-9a-fA-F-]+)\]\]$/);
                if (match) {
                    var uid = match[1];
                    var fData = formulasMap[uid];
                    var renderedNode = _renderFormula(
                        uid,
                        fData,
                        Object.prototype.hasOwnProperty.call(formulasMap, uid) && !!fData._temporary
                    );
                    fragment.appendChild(renderedNode);
                } else if (part) {
                    fragment.appendChild(document.createTextNode(part));
                }
            });

            parent.replaceChild(fragment, textNode);
        });

        // Trigger MathJax styles update
        if (window.MathJax && window.MathJax.startup && window.MathJax.startup.document) {
            window.MathJax.startup.document.clear();
            window.MathJax.startup.document.updateDocument();
        }
    }

    /**
     * Render a single formula with the full fallback chain.
     * Returns a DOM node ready for insertion.
     */
    function _renderFormula(uid, fData, isTemporary) {
        if (!fData) {
            return _createErrorSpan('[Không tìm thấy công thức]');
        }

        var conversionStatus = fData.conversion_status || fData.status;
        var verificationStatus = fData.verification_status;

        // Status: pending → show spinner with polling
        if (conversionStatus === 'pending') {
            // MathType OLE contains a faithful WMF/EMF preview. Show it
            // immediately while the optional worker converts MTEF in the
            // background, so review never displays a missing formula.
            if (fData.preview_url) {
                var preview = document.createElement('img');
                preview.src = fData.preview_url;
                preview.alt = 'Công thức MathType';
                preview.className = 'formula-mathtype-preview';
                preview.style.cssText = 'display:inline-block;vertical-align:middle;max-height:45px;max-width:100%;margin:0 4px;';
                preview.title = 'Đang chuẩn bị dữ liệu công thức MathType';
                return preview;
            }

            // A static SVG preview saved during import is also exposed through
            // svg_cache_key after the FormulaAsset is persisted.
            if (fData.svg_cache_key && fData.svg_cache_key.indexOf('/static/') === 0) {
                return _createCachedSvgElement(fData.svg_cache_key, verificationStatus);
            }

            // Temporary preview IDs do not exist in the database yet, and a
            // missing worker can never complete a conversion. Do not poll a
            // job that cannot make progress.
            if (isTemporary || fData.worker_available === false) {
                return _createErrorSpan('[Chưa có bản hiển thị công thức MathType]');
            }
            return _createPendingSpinner(uid);
        }

        // Status: failed → show friendly error
        if (conversionStatus === 'failed') {
            return _createErrorSpan('[Không thể chuyển đổi công thức]');
        }

        // Status: fallback_svg → go directly to SVG
        if (conversionStatus === 'fallback_svg') {
            if (fData.svg_cache_key && fData.svg_cache_key.indexOf('/static/') === 0) {
                return _createCachedSvgElement(fData.svg_cache_key, verificationStatus);
            }
            return _createSvgElement(uid, verificationStatus);
        }

        // Try MathML first (highest priority)
        if (fData.mathml) {
            try {
                var mathNode = window.MathJax.mathml2chtml(fData.mathml);
                return _wrapWithReviewStatus(mathNode, verificationStatus);
            } catch (e) {
                console.warn('[FormulaRenderer] MathML render failed, trying LaTeX:', e.message);
            }
        }

        // Fallback 1: LaTeX
        if (fData.latex) {
            try {
                var latexNode = window.MathJax.tex2chtml(fData.latex);
                return _wrapWithReviewStatus(latexNode, verificationStatus);
            } catch (e) {
                console.warn('[FormulaRenderer] LaTeX render failed, trying SVG:', e.message);
            }
        }

        // Fallback 2: SVG from worker endpoint
        if (fData.svg_cache_key || fData.source_format === 'MathType') {
            return _createSvgElement(uid, verificationStatus);
        }

        // Everything failed
        return _createErrorSpan('[Lỗi hiển thị công thức]');
    }

    /**
     * Create a pending spinner element with auto-polling.
     */
    function _createPendingSpinner(uid) {
        var wrapper = document.createElement('span');
        wrapper.className = 'formula-pending';
        wrapper.setAttribute('data-formula-id', uid);
        wrapper.style.cssText = 'display:inline-block;margin:0 4px;padding:2px 8px;background:rgba(255,193,7,0.1);border-radius:4px;color:#856404;font-size:0.85em;';

        var spinner = document.createElement('span');
        spinner.className = 'formula-spinner';
        spinner.style.cssText = 'display:inline-block;width:14px;height:14px;border:2px solid #ffc107;border-top-color:transparent;border-radius:50%;animation:formula-spin 0.8s linear infinite;vertical-align:middle;margin-right:6px;';
        wrapper.appendChild(spinner);

        var text = document.createTextNode('Đang chuyển đổi công thức…');
        wrapper.appendChild(text);

        // Add CSS animation if not already added
        _ensureSpinnerCSS();

        // Start polling
        _startPolling(uid, wrapper);

        return wrapper;
    }

    /**
     * Create SVG fallback element using secure <img> tag.
     */
    function _createSvgElement(uid, verificationStatus) {
        var img = document.createElement('img');
        img.src = '/api/formulas/' + encodeURIComponent(uid) + '/render.svg';
        img.alt = 'Công thức toán';
        img.className = 'formula-svg';
        img.style.cssText = 'display:inline-block;vertical-align:middle;max-height:45px;margin:0 4px;';
        img.onerror = function() {
            var errorSpan = _createErrorSpan('[Lỗi hiển thị công thức]');
            if (img.parentNode) {
                img.parentNode.replaceChild(errorSpan, img);
            }
        };
        return _wrapWithReviewStatus(img, verificationStatus);
    }

    function _createCachedSvgElement(url, verificationStatus) {
        var img = document.createElement('img');
        img.src = url;
        img.alt = 'Công thức toán';
        img.className = 'formula-svg';
        img.style.cssText = 'display:inline-block;vertical-align:middle;max-height:45px;max-width:100%;margin:0 4px;';
        img.onerror = function() {
            var errorSpan = _createErrorSpan('[Lỗi hiển thị công thức]');
            if (img.parentNode) img.parentNode.replaceChild(errorSpan, img);
        };
        return _wrapWithReviewStatus(img, verificationStatus);
    }

    /**
     * Create a friendly error message span.
     */
    function _createErrorSpan(message) {
        var span = document.createElement('span');
        span.className = 'formula-error text-danger text-sm fst-italic';
        span.style.cssText = 'display:inline;font-size:0.85em;color:#dc3545;font-style:italic;';
        span.textContent = message;
        return span;
    }

    /**
     * Wrap a math node with review indicator if needed.
     */
    function _wrapWithReviewStatus(mathNode, verificationStatus) {
        if (verificationStatus === 'needs_review') {
            var wrapper = document.createElement('span');
            wrapper.style.cssText = 'border-bottom:2px dashed orange;position:relative;display:inline-block;margin:0 4px;cursor:help;';
            wrapper.title = 'Công thức cần kiểm tra lại độ chính xác';
            wrapper.appendChild(mathNode);
            return wrapper;
        }

        mathNode.style.display = 'inline-block';
        mathNode.style.margin = '0 4px';
        return mathNode;
    }

    /**
     * Ensure spinner CSS animation exists in document.
     */
    var _spinnerCSSAdded = false;
    function _ensureSpinnerCSS() {
        if (_spinnerCSSAdded) return;
        var style = document.createElement('style');
        style.textContent = '@keyframes formula-spin { to { transform: rotate(360deg); } }';
        document.head.appendChild(style);
        _spinnerCSSAdded = true;
    }

    /**
     * Start polling for a pending formula.
     */
    function _startPolling(uid, element) {
        if (_pendingPolls.has(uid)) return;

        var retryCount = 0;
        var csrfTokenMeta = document.querySelector('meta[name="csrf-token"]');
        var csrfToken = csrfTokenMeta ? csrfTokenMeta.getAttribute('content') : '';

        var intervalId = setInterval(function() {
            retryCount++;
            if (retryCount > PENDING_MAX_RETRIES) {
                clearInterval(intervalId);
                _pendingPolls.delete(uid);
                if (element.parentNode) {
                    var errorSpan = _createErrorSpan('[Công thức chưa sẵn sàng]');
                    element.parentNode.replaceChild(errorSpan, element);
                }
                return;
            }

            fetch('/api/formulas/batch', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ uuids: [uid] })
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success && data.formulas && data.formulas[uid]) {
                    var fData = data.formulas[uid];
                    var status = fData.conversion_status;

                    if (status !== 'pending') {
                        // Conversion completed or failed
                        clearInterval(intervalId);
                        _pendingPolls.delete(uid);

                        if (element.parentNode) {
                            var renderedNode = _renderFormula(uid, fData);
                            element.parentNode.replaceChild(renderedNode, element);

                            // Update MathJax
                            if (window.MathJax && window.MathJax.startup && window.MathJax.startup.document) {
                                window.MathJax.startup.document.clear();
                                window.MathJax.startup.document.updateDocument();
                            }
                        }
                    }
                }
            })
            .catch(function(err) {
                console.warn('[FormulaRenderer] Poll error:', err);
            });
        }, PENDING_POLL_INTERVAL);

        _pendingPolls.set(uid, intervalId);
    }

    // Public API
    return {
        renderFormulas: renderFormulas
    };
})();

// Backward compatibility
window.renderFormulas = window.FormulaRenderer.renderFormulas;
