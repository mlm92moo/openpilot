"""Token handling for the local-only speed-limit portal."""
import hmac
import secrets


TOKEN_PARAM = "SpeedLimitPortalToken"


def ensure_token(params, token_factory=secrets.token_urlsafe):
  token = params.get(TOKEN_PARAM, return_default=True)
  if token is None:
    token = token_factory(24)
    if type(token) is not str or len(token) < 24:
      raise ValueError("token generator returned an unsafe token")
    params.put(TOKEN_PARAM, token, block=True)
  if type(token) is not str or len(token) < 24:
    raise ValueError("stored portal token is invalid")
  return token


def authorized(authorization, token):
  if type(authorization) is not str or type(token) is not str:
    return False
  prefix = "Bearer "
  return authorization.startswith(prefix) and hmac.compare_digest(authorization[len(prefix):], token)
