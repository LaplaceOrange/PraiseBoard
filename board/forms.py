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
        fields = ("student_no", "name", "is_active")
        widgets = {
            "student_no": forms.TextInput(attrs={"class": "pb-input", "autocomplete": "off"}),
            "name": forms.TextInput(attrs={"class": "pb-input", "autocomplete": "off"}),
        }


class RosterUploadForm(forms.Form):
    file = forms.FileField(
        label="名单文件",
        help_text="支持 CSV 或 XLSX。表格需要包含“学号”和“姓名”两列。",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,.xlsx", "class": "pb-input"}),
    )
