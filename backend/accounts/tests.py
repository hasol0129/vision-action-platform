from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class AccountTests(TestCase):
    def test_signup_creates_user_and_logs_in(self):
        res = self.client.post(reverse('signup'), {
            'username': 'newbie', 'password1': 'VisionPass!2026', 'password2': 'VisionPass!2026',
        })
        self.assertRedirects(res, reverse('analyses:index'))
        self.assertTrue(User.objects.filter(username='newbie').exists())
        self.assertEqual(int(self.client.session['_auth_user_id']), User.objects.get(username='newbie').pk)

    def test_signup_password_mismatch_shows_error(self):
        res = self.client.post(reverse('signup'), {
            'username': 'newbie', 'password1': 'VisionPass!2026', 'password2': 'different!2026',
        })
        self.assertEqual(res.status_code, 200)
        self.assertFalse(User.objects.filter(username='newbie').exists())

    def test_login_and_logout(self):
        User.objects.create_user('alice', password='VisionPass!2026')
        res = self.client.post(reverse('login'), {'username': 'alice', 'password': 'VisionPass!2026'})
        self.assertRedirects(res, reverse('analyses:index'))
        res = self.client.post(reverse('logout'))
        self.assertRedirects(res, reverse('login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_anonymous_is_redirected_from_pages(self):
        res = self.client.get(reverse('analyses:index'))
        self.assertRedirects(res, f"{reverse('login')}?next=/analyses/")

    def test_duplicate_username_shows_error(self):
        User.objects.create_user('alice', password='VisionPass!2026')
        res = self.client.post(reverse('signup'), {
            'username': 'alice', 'password1': 'VisionPass!2026', 'password2': 'VisionPass!2026',
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.context['form'].errors.get('username'))
        self.assertEqual(User.objects.filter(username='alice').count(), 1)

    def test_guide_urls(self):
        self.assertEqual(reverse('signup'), '/accounts/signup/')
        self.assertEqual(reverse('login'), '/accounts/login/')
        self.assertEqual(reverse('analyses:index'), '/analyses/')
        self.assertRedirects(self.client.get('/'), '/analyses/', target_status_code=302)

    def test_anonymous_cannot_use_api(self):
        res = self.client.get('/api/analyses/')
        self.assertIn(res.status_code, (401, 403))
