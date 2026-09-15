import unittest

from openpilot.custom.speed_limit.portal_auth import authorized, ensure_token


class FakeParams:
  def __init__(self):
    self.value = None

  def get(self, *_args, **_kwargs):
    return self.value

  def put(self, _key, value, block=False):
    self.value = value


class PortalAuthTests(unittest.TestCase):
  def test_token_is_persisted_and_required_as_bearer(self):
    params = FakeParams()
    token = ensure_token(params, lambda _: "a" * 24)
    self.assertEqual(token, ensure_token(params))
    self.assertTrue(authorized("Bearer " + token, token))
    self.assertFalse(authorized(token, token))
    self.assertFalse(authorized("Bearer wrong", token))
