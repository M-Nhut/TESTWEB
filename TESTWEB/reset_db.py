from app import app, db
import os

# 1. Xóa file cũ nếu có
db_path = "library.db"
if os.path.exists(db_path):
    os.remove(db_path)
    print("Đã xóa database cũ.")

# 2. Tạo database mới
with app.app_context():
    db.create_all()
    print("Đã tạo bảng mới thành công (User, Book, Author,...)!")
    
    # (Tùy chọn) Tạo luôn dữ liệu mẫu ở đây nếu muốn
    from app import create_sample_data
    create_sample_data()