from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model

User = get_user_model()

class SignupForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('email', 'username')
        labels = {
            'email': '이메일 주소',
            'username': '닉네임',
        }
        error_messages = {
            'email': {
                'unique': "이미 가입된 이메일입니다. 다른 이메일을 사용해 주세요."
            }
        }
        # 💡 [추가] 150자 안내 문구를 15자로 변경
        help_texts = {
            'username': '15자 이내의 문자와 숫자로만 입력해 주세요.',
        }

    # 💡 [추가] 실제 HTML 폼에도 최대 길이를 15자로 강제 고정
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].max_length = 15
        self.fields['username'].widget.attrs['maxlength'] = '15'

    # 닉네임 중복 방지 로직 (기존과 동일)
    def clean_username(self):
        username = self.cleaned_data.get('username').strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("이미 사용 중인 닉네임입니다. 다른 닉네임을 입력해 주세요.")
        return username