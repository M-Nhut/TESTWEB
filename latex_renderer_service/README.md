# LaTeX Renderer Service

Service server-side dùng để render các block LaTeX mà MathJax không hỗ trợ,
đặc biệt là `tikzpicture` và `tabular`. Browser của người dùng không cần cài
LaTeX hay MathType.

## Chạy bằng Docker

```bash
docker build -t question-latex-renderer latex_renderer_service
docker run --rm -p 8080:8080 question-latex-renderer
```

Đặt trong web app:

```env
LATEX_RENDERER_URL=http://localhost:8080
```

Production có thể deploy image này lên Cloud Run, Render, Railway hoặc VPS.
Service chỉ nhận source LaTeX, không bật `shell-escape`, giới hạn 200 KB và
timeout mỗi lượt biên dịch.

Để bảo vệ endpoint công khai, đặt cùng một token ở renderer và web app:

```env
LATEX_RENDERER_TOKEN=thay-bang-chuoi-bi-mat-dai
```

Health check: `GET /health`.
