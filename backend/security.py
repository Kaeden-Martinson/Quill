"""Password hashing, session tokens, and login rate limiting."""
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

SESSION_DAYS = 30


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password, stored):
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return hmac.compare_digest(actual.hex(), digest)


def new_token():
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token):
    # Only the hash is stored, so a leaked database can't be used to sign in.
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip(request):
    """Real visitor IP. Tunnels connect from localhost and pass the visitor in a header."""
    host = request.client.host if request.client else "unknown"
    if host in ("127.0.0.1", "::1"):
        forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return host


class RateLimiter:
    """Allows `limit` failures per `window` seconds for each key."""

    def __init__(self, limit, window):
        self.limit, self.window = limit, window
        self.failures = defaultdict(deque)

    def _prune(self, key):
        q = self.failures[key]
        cutoff = time.monotonic() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked(self, key):
        return len(self._prune(key)) >= self.limit

    def fail(self, key):
        self._prune(key).append(time.monotonic())

    def reset(self, key):
        self.failures.pop(key, None)


# Per visitor IP, and per account name so one account can't be brute-forced from many IPs.
by_ip = RateLimiter(limit=10, window=15 * 60)
by_name = RateLimiter(limit=5, window=15 * 60)
