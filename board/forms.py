from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import ValidationError

from .models import User, Student


class AdminTeacherCreationForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("username", "display_name", "email")


class TeacherLoginForm(forms.Form):
    identity = forms.IntegerField(widget=forms.HiddenInput)
    password = forms.CharField(
        label="密码",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "class": "pb-input"}),
    )


class AdminLoginForm(forms.Form):
    username = forms.CharField(
        label="管理员账号",
        widget=forms.TextInput(attrs={"autocomplete": "username", "class": "pb-input"}),
    )
    password = forms.CharField(
        label="密码",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "class": "pb-input"}),
    )


class SecurePasswordChangeForm(PasswordChangeForm):
    def clean_new_password2(self):
        password = self.cleaned_data.get("new_password2") or ""
        if password.isdigit():
            raise ValidationError("新密码不能全部是数字。")
        if self.user.check_password(password):
            raise ValidationError("新密码不能与原密码相同。")
        if password != self.cleaned_data.get("new_password1"):
            raise ValidationError("两次输入的新密码不一致。")
        return password


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = ("student_no", "name", "seat_order", "group", "responsibility", "is_active")
        widgets = {
            "student_no": forms.TextInput(attrs={"class": "pb-input", "autocomplete": "off"}),
            "name": forms.TextInput(attrs={"class": "pb-input", "autocomplete": "off"}),
            "seat_order": forms.NumberInput(attrs={"class": "pb-input", "min": "0"}),
            "group": forms.TextInput(attrs={"class": "pb-input"}),
            "responsibility": forms.TextInput(attrs={"class": "pb-input"}),
        }


class RosterUploadForm(forms.Form):
    file = forms.FileField(
        label="名单文件",
        help_text="支持 CSV 或 XLSX。表格需要包含“学号”和“姓名”两列。",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,.xlsx", "class": "pb-input"}),
    )


class ExamRadarUploadForm(forms.Form):
    title = forms.CharField(
        label="考试名称",
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={"class": "pb-input", "placeholder": "如：八下期末"}),
    )
    sheet_name = forms.CharField(
        label="工作表名称",
        max_length=31,
        required=False,
        widget=forms.TextInput(attrs={"class": "pb-input", "placeholder": "留空读取第一个工作表"}),
    )
    file = forms.FileField(
        label="成绩文件",
        help_text="XLSX 格式，需包含学号、姓名、七科成绩及 60、75、85、92 号参考线。",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx", "class": "pb-input"}),
    )

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        if not uploaded_file.name.lower().endswith(".xlsx"):
            raise ValidationError("请上传 XLSX 格式的成绩文件。")
        if uploaded_file.size > 10 * 1024 * 1024:
            raise ValidationError("成绩文件不能超过 10 MB。")
        return uploaded_file
