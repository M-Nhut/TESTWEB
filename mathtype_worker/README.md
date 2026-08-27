# MathType Conversion Worker

## Tổng quan

Worker này chạy trên **Windows** với **MathType SDK** đã cài đặt và kích hoạt bằng license hợp lệ. Nó cung cấp REST API để Flask app gọi chuyển đổi dữ liệu MTEF binary sang MathML, LaTeX và SVG vector.

## Yêu cầu hệ thống

| Yêu cầu | Chi tiết |
|----------|----------|
| **Hệ điều hành** | Windows 10/11 hoặc Windows Server 2019+ |
| **MathType SDK** | Phải được cài đặt và kích hoạt bằng license do chủ hệ thống cung cấp |
| **Python** | 3.8+ |
| **Thư viện** | Flask, comtypes (cho COM automation) |

> ⚠️ **QUAN TRỌNG**: 
> - Worker này **KHÔNG** chạy được trên Linux/macOS hoặc Vercel
> - MathType SDK/license **PHẢI** do chủ hệ thống tự cài đặt và kích hoạt
> - Không có cách chạy MathType SDK trong Flask app trên Vercel/Linux

## Cài đặt

### 1. Cài MathType SDK trên Windows

1. Tải MathType SDK từ Wiris/MathType
2. Cài đặt theo hướng dẫn của nhà phát hành
3. Kích hoạt license
4. Đảm bảo COM object `MathTypeSDK.Application` có sẵn

### 2. Cài Python dependencies

```bash
pip install flask comtypes
```

### 3. Cấu hình biến môi trường

```bash
# Token xác thực (BẮT BUỘC trong production)
set MATHTYPE_WORKER_TOKEN=your-secret-token-here

# Port (mặc định: 8081) 
set MATHTYPE_WORKER_PORT=8081

# Thư mục cache SVG (mặc định: ./svg_cache)
set MATHTYPE_SVG_CACHE_DIR=C:\mathtype_worker\svg_cache

# TTL cache SVG tính bằng giây (mặc định: 86400 = 24 giờ)
set MATHTYPE_SVG_CACHE_TTL=86400
```

### 4. Chạy worker

```bash
python worker.py
```

Worker sẽ lắng nghe tại `http://0.0.0.0:8081`.

## API Endpoints

### `GET /health`
Kiểm tra trạng thái worker và SDK.

### `POST /api/convert`
Chuyển đổi MTEF sang MathML/LaTeX.

**Request:**
```json
{
  "mtef_base64": "<zlib-compressed base64 MTEF>",
  "formula_hash": "<SHA-256 hash>"
}
```

**Response (200):**
```json
{
  "mathml": "<math>...</math>",
  "latex": "\\frac{1}{2}",
  "svg_url": "/api/render-svg?hash=abc123",
  "converter_name": "MathTypeSDK",
  "converter_version": "7.0",
  "confidence": 1.0
}
```

### `POST /api/render-svg`
Render MTEF thành SVG vector.

**Request:**
```json
{
  "mtef_base64": "<zlib-compressed base64 MTEF>",
  "formula_hash": "<SHA-256 hash>"
}
```

**Response:** SVG file với `Content-Type: image/svg+xml`

### `GET /api/render-svg?hash=<formula_hash>`
Lấy SVG đã cache theo hash.

## Cấu hình Flask App (phía server chính)

Trên Flask app (Linux/Vercel), cấu hình biến môi trường:

```bash
# URL của worker Windows
export MATHTYPE_WORKER_URL=http://192.168.1.100:8081

# Token xác thực (phải khớp với MATHTYPE_WORKER_TOKEN trên worker)
export MATHTYPE_WORKER_TOKEN=your-secret-token-here
```

## Bảo mật

- Mọi request phải có header `Authorization: Bearer <token>`
- Token không được hard-code, lấy từ biến môi trường
- Worker chỉ nên chạy trong mạng nội bộ hoặc qua VPN
- Trong production, dùng HTTPS reverse proxy (nginx/IIS)

## Cache

- SVG được cache trên filesystem theo SHA-256 hash của MTEF
- Cache có TTL (mặc định 24 giờ)
- Conversion results được cache in-memory (theo process lifetime)
- Không lưu SVG binary trong database SQLite

## Triển khai thực tế

### Chưa có MathType SDK
Nếu chưa có MathType SDK/license:
- Flask app vẫn hoạt động bình thường
- FormulaAsset MathType sẽ có `conversion_status = "pending"`
- Frontend hiển thị spinner "Đang chuyển đổi công thức…"
- Khi worker được cấu hình, chạy lại conversion cho các asset pending

### Implement SDK Adapter
File `worker.py` chứa class `MathTypeSDKAdapter` với interface sẵn. Cần implement 3 method:
- `convert_mtef_to_mathml(mtef_bytes) -> str`
- `convert_mtef_to_latex(mtef_bytes) -> str`  
- `render_mtef_to_svg(mtef_bytes) -> bytes`

Implement bằng `comtypes` để gọi COM object của MathType SDK.
