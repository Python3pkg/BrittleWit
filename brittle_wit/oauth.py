"""
This module contains a bare-bones OAuth implementation. It is
minimally-compliant so as to conform to Twitter's requirements.

See: https://dev.twitter.com/oauth/overview
"""

import binascii
import hashlib
import hmac
import random
import time

from functools import total_ordering
from urllib.parse import quote as urllib_quote

from brittle_wit import __version__

ANY_CREDENTIALS = None

ALPHANUMERIC = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
USER_AGENT = 'BrittleWit/' + __version__


def _quote(s):
    if type(s) is int or type(s) is float:
        s = str(s)
    elif s is True:
        s = 'true'
    elif s is False:
        s = 'false'

    return urllib_quote(s, safe='')


def _generate_nonce(length=42):
    """
    Generate an alpha numeric string that is unique for each request.

    Twitter used a 42 character alpha-numeric (case-sensitive) string in the
    API documentation. However, they note "any approach which produces a
    relatively random alphanumeric string should be OK here." I opted not to
    use a cryptographically secure source of entropy. `SystemRandom` is
    convenient, but it uses file IO to connect to `/dev/urandom`. Adding
    `async` machinery here seems like expensive complexity.
    """
    return "".join(random.choice(ALPHANUMERIC) for _ in range(length))


def _generate_timestamp():
    return int(time.time())


def _generate_header_string(params):
    """
    Generate the string for use in the http "Authorization" header field.

    :param params: a dictionary with the oauth_* key-values.
    """
    return "OAuth " + ", ".join('{}="{}"'.format(k, _quote(params[k]))
                                for k in sorted(params))


def _generate_param_string(params):
    """
    Generate the parameter string for signing.

    :param params: A dictionary with both the request and oauth_* parameters,
        less the `oauth_signature`.
    """
    d = {_quote(k): _quote(v) for k, v in params.items()}
    return "&".join(["{}={}".format(k, d[k]) for k in sorted(d)])


def _generate_sig_base_string(method, base_url, param_string):
    """
    :param method: either `get` or `post`
    :param base_url: the API base URL (i.e. without parameters)
    :param param_string: string generated by generate_param_string
    """
    return "&".join([method.upper(), _quote(base_url), _quote(param_string)])


def _generate_signing_key(consumer_secret, oauth_token_secret):
    return "{}&{}".format(_quote(consumer_secret), _quote(oauth_token_secret))


def _generate_signature(sig_base_string, signing_key):
    digest = hmac.new(signing_key.encode('ascii'),
                      sig_base_string.encode('ascii'),
                      hashlib.sha1).digest()

    return binascii.b2a_base64(digest)[:-1]  # Strip newline


def generate_req_headers(twitter_req, app_cred, client_cred, **overrides):
    """
    Generate the 'Authorization' and 'User-Agent' headers.

    :param twitter_req: A TwitterRequest object
    :param app_cred: an AppCredentials object
    :param client_cred: a ClientCredentials object
    :param overrides: key-value pairs which override (or, adds a new value
        to) the oauth_* dictionary used for signature generation.
    """
    oauth_d = {'oauth_consumer_key': app_cred.key,
               'oauth_nonce': _generate_nonce(),
               'oauth_signature_method': "HMAC-SHA1",
               'oauth_timestamp': str(_generate_timestamp()),
               'oauth_token': client_cred.token,
               'oauth_version': "1.0"}

    if overrides:
        oauth_d.update(overrides)

    param_string = _generate_param_string({**oauth_d, **twitter_req.params})
    sig_base_string = _generate_sig_base_string(twitter_req.method,
                                                twitter_req.url,
                                                param_string)
    signing_key = _generate_signing_key(app_cred.secret, client_cred.secret)
    oauth_d['oauth_signature'] = _generate_signature(sig_base_string,
                                                     signing_key)

    return {'Authorization': _generate_header_string(oauth_d),
            'User-Agent': USER_AGENT}


class AppCredentials:
    """
    An Immutable set of application credentials.
    """

    __slots__ = '_key', '_secret'

    def __init__(self, key, secret):
        self._key, self._secret = key, secret

    @property
    def key(self):
        return self._key

    @property
    def secret(self):
        return self._secret

    def __str__(self):
        s = "AppCredentials({}, {})"
        return s.format(self._key, "*" * len(self._secret))

    def __repr__(self):
        return self.__str__()

    def __hash__(self):
        return hash((self._key, self._secret))

    def __eq__(self, other):
        return self.key == self.key and self.secret == other.secret

    def __ne__(self, other):
        return not self == other


@total_ordering
class ClientCredentials:
    """
    An Immutable set of client credentials.

    Note: Equality testing and hashing is a function of the user_id alone!
    """

    __slots__ = '_user_id', '_token', '_secret'

    def __init__(self, user_id, token, secret):
        self._user_id, self._token, self._secret = user_id, token, secret

    @property
    def token(self):
        return self._token

    @property
    def secret(self):
        return self._secret

    @property
    def user_id(self):
        return self._user_id

    @property
    def as_dict(self):
        return {'user_id': self._user_id,
                'token': self._token,
                'secret': self._secret}

    @staticmethod
    def from_dict(d):
        return ClientCredentials(d['user_id'], d['token'], d['secret'])

    def __str__(self):
        s = "ClientCredentials({}, {}, {})"
        return s.format(self.user_id, self._token, "*" * len(self._secret))

    def __repr__(self):
        return self.__str__()

    def __hash__(self):
        return hash(self._user_id)

    def __eq__(self, other):
        return self.user_id == other.user_id

    def __ne__(self, other):
        return not self == other

    def __lt__(self, other):
        # Because the client_credentials may partially-determine ordering
        # in a priority queue.
        return self.user_id < other.user_id
