import json

from django.test import Client, SimpleTestCase


class HealthEndpointContractTests(SimpleTestCase):
    """Contract tests for GET /api/health/ (no database access)."""

    def setUp(self) -> None:
        self.client = Client()

    def test_get_health_returns_stable_json(self) -> None:
        response = self.client.get('/api/health/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertEqual(
            json.loads(response.content),
            {'status': 'ok', 'service': 'agentworkspace'},
        )

    def test_post_health_is_rejected(self) -> None:
        response = self.client.post('/api/health/')

        self.assertEqual(response.status_code, 405)

    def test_post_health_with_csrf_enforcement_is_still_rejected(self) -> None:
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post('/api/health/')

        self.assertEqual(response.status_code, 405)


class HomePageContractTests(SimpleTestCase):
    """Contract test for the bootstrap home page (no database access)."""

    def test_home_page_shows_service_state_and_health_link(self) -> None:
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn('AI协作工作台', html)
        self.assertIn('Django服务已启动', html)
        self.assertIn('href="/api/health/"', html)
        self.assertIn('href="/workspace/"', html)
        self.assertIn('href="/projects/"', html)
        self.assertIn('no-store', response['Cache-Control'])
