from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import redirect, render


def signup(request):
    """Django 기본 User로 회원가입 후 바로 로그인시킨다."""
    if request.user.is_authenticated:
        return redirect('analyses:index')

    form = UserCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect('analyses:index')
    return render(request, 'accounts/signup.html', {'form': form})
