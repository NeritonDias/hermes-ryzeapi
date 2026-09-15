import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import test_ryzeapi
from ryzeapi.infrastructure import validate,load,health_url

class DeploymentTests(unittest.TestCase):
    def test_safe_defaults_do_not_point_to_another_installation(self):
        with tempfile.TemporaryDirectory() as home,patch('ryzeapi.infrastructure.directory',return_value=Path(home)):
            self.assertEqual(load()['public_origin'],'http://localhost:9119')
            self.assertEqual(load()['webhook_url'],'')
            self.assertEqual(health_url(),'http://127.0.0.1:9120/health')
    def test_custom_origin_service_and_port(self):
        result=validate({'public_origin':'https://agent.example.com','webhook_url':'https://hooks.example.com/ryzeapi/events','listener_port':9125,'gateway_service':'hermes-work.service'})
        self.assertEqual(result['listener_port'],9125)
    def test_reject_unsafe_configuration(self):
        for value in ({'public_origin':'https://example.com/path'},{'public_origin':'http://example.com'},
                      {'public_origin':'https://user:pass@example.com'},{'webhook_url':'https://127.0.0.1/ryzeapi/events'},
                      {'webhook_url':'https://example.com/wrong'},{'listener_port':True},{'listener_port':80},
                      {'gateway_service':'x;curl evil'},{'unknown':1}):
            with self.subTest(value=value),self.assertRaises(ValueError):validate(value)
