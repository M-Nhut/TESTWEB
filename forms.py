from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import StringField, PasswordField, SelectField, TelField, DateField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, EqualTo, ValidationError
from flask_login import current_user
from models import User

# ──────────────────────── FORMS ────────────────────────

class RegistrationForm(FlaskForm):
    user_code = StringField("Mã người dùng", validators=[DataRequired(), Length(min=3, max=20)])
    fullname = StringField("Họ và tên", validators=[DataRequired(), Length(min=2, max=100)])
    username = StringField("Tên đăng nhập", validators=[DataRequired(), Length(min=4, max=80)])
    phone = TelField("Số điện thoại", validators=[Optional()])
    parent_phone = TelField("SĐT phụ huynh", validators=[Optional()])
    position = StringField("Lớp / Chức vụ", validators=[Optional(), Length(max=100)])
    role = SelectField(
        "Vai trò",
        choices=[("student", "Học sinh"), ("teacher", "Giáo viên"), ("parent", "Phụ huynh")],
        validators=[DataRequired()],
    )
    password = PasswordField("Mật khẩu", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField("Nhập lại mật khẩu", validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Đăng ký")

    def validate_username(self, username):
        if User.query.filter_by(username=username.data).first():
            raise ValidationError("Tên đăng nhập đã tồn tại.")

    def validate_user_code(self, user_code):
        if User.query.filter_by(user_code=user_code.data).first():
            raise ValidationError("Mã người dùng đã tồn tại.")

    def validate_role(self, role):
        if role.data in ("admin", "manager"):
            raise ValidationError("Không thể đăng ký vai trò này.")


class LoginForm(FlaskForm):
    username = StringField("Tên đăng nhập", validators=[DataRequired()])
    password = PasswordField("Mật khẩu", validators=[DataRequired()])
    submit = SubmitField("Đăng nhập")


class UpdateProfileForm(FlaskForm):
    fullname = StringField("Họ và tên", validators=[DataRequired(), Length(min=2)])
    username = StringField("Tên đăng nhập", validators=[DataRequired(), Length(min=4)])
    phone = TelField("Số điện thoại", validators=[Optional()])
    parent_phone = TelField("SĐT phụ huynh", validators=[Optional()])
    position = StringField("Lớp / Chức vụ", validators=[Optional(), Length(max=100)])
    birth_date = DateField("Ngày sinh", validators=[Optional()])
    avatar = FileField("Avatar", validators=[FileAllowed(["jpg", "png", "jpeg"], "Chỉ nhận file ảnh!")])
    submit_profile = SubmitField("Cập nhật")

    def validate_username(self, username):
        if username.data != current_user.username and User.query.filter_by(username=username.data).first():
            raise ValidationError("Tên đăng nhập này đã có người sử dụng.")


class ChangePasswordForm(FlaskForm):
    old_password = PasswordField("Mật khẩu cũ", validators=[DataRequired()])
    new_password = PasswordField("Mật khẩu mới", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField("Xác nhận mật khẩu mới", validators=[DataRequired(), EqualTo("new_password")])
    submit_password = SubmitField("Đổi mật khẩu")
