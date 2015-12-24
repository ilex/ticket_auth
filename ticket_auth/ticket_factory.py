import time
from struct import pack
import hashlib
import urllib.parse as ulp
import ipaddress
from ipaddress import ip_address
from collections import namedtuple
from .exception import *  # noqa


"""Tuple type used to describe a tickets parts"""
TicketInfo = namedtuple('TicketInfo', ['digest', 'user_id', 'tokens',
                                       'user_data', 'valid_until'])


class TicketFactory(object):
    """Cookie authentication class, influenced by apaches mod_auth_tkt,
    with support for different hash algorithms and ip6
    """

    # Default timeout in seconds
    _DEFAULT_TIMEOUT = 120

    # Default ip address to use if no client ip is specified
    _DEFAULT_IP = ipaddress.IPv4Address('0.0.0.0')

    def __init__(self, secret, hashalg='sha512'):
        """Initializes the ticket factory with the secret used to encode the
        tickets
        """
        self._secret = secret
        self._hash = hashlib.new(hashalg)

    def new(self, user_id, tokens=None, user_data=None, valid_until=None,
            client_ip=None, encoding='utf-8'):
        """Creates a new authentication ticket, returned as a string.
        """
        if valid_until is None:
            valid_until = int(time.time()) + TicketFactory._DEFAULT_TIMEOUT

        # Make sure we dont have any exclamations in the user_id
        user_id = ulp.quote(user_id)

        # Create a comma seperated list of tokens
        token_str = ''
        if tokens:
            # Escape characters in our tokens
            token_str = ','.join((ulp.quote(t) for t in tokens))

        # Encode our user data (a string)
        user_str = '' if not user_data else ulp.quote(user_data)

        # Get our address
        ip = self._DEFAULT_IP if client_ip is None else ip_address(client_ip)

        # Create our digest
        data0 = bytes([ip.version]) + ip.packed + pack(">I", valid_until)
        data1 = ('\0'.join((user_id, token_str, user_str))).encode(encoding)
        digest = self._hexdigest(data0, data1)

        # digest + timestamp as an eight character hexadecimal + userid
        parts = ('{0}{1:08x}{2}'.format(digest, valid_until, user_id),
                 token_str, user_str)
        return '!'.join(parts)

    def validate(self, ticket, client_ip=None, now=None, encoding='utf-8'):
        """Validates the passed ticket, returns a TicketInfo tuple containing
        the users authentication details on success, raises a TicketError
        on failure
        """
        parts = self.parse(ticket)

        # Check if our ticket matches
        new_ticket = self.new(*(parts[1:]), client_ip, encoding)

        if new_ticket[:self._hash.digest_size * 2] != parts.digest:
            raise TicketDigestError(ticket)

        if now is None:
            now = time.time()

        if parts.valid_until <= now:
            raise TicketExpired(ticket)

        return parts

    def parse(self, ticket):
        """Parses the passed ticket, returning a tuple containing the digest,
        user_id, valid_until, tokens, and user_data fields
        """
        if len(ticket) < self._min_ticket_size():
            raise TicketParseError(ticket, 'Invalid ticket length')

        digest_len = self._hash.digest_size * 2
        digest = ticket[:digest_len]

        try:
            time_len = 8
            time = int(ticket[digest_len:digest_len + time_len], 16)
        except:
            raise TicketParseError(ticket, 'Invalid time field')

        parts = ticket[digest_len + time_len:].split('!')
        if len(parts) != 3:
            raise TicketParseError(ticket, 'Missing parts')

        user_id = ulp.unquote(parts[0])
        tokens = ()
        if parts[1]:
            tokens = tuple((ulp.unquote(t) for t in parts[1].split(',')))

        user_data = ulp.unquote(parts[2])

        return TicketInfo(digest, user_id, tokens, user_data, time)

    def _min_ticket_size(self):
        # Digest length plus time length (we allow empty user_id's)
        return (self._hash.digest_size * 2 + 8)

    def _hexdigest(self, data0, data1):
        hash0 = self._hash.copy()
        hash0.update(data0 + self._secret + data1)

        hash1 = self._hash.copy()
        hash1.update(hash0.digest() + self._secret)
        return hash1.hexdigest()