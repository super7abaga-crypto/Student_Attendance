import hashlib
import hmac
from django.contrib.auth.hashers import BasePasswordHasher


class LegacyNodeScryptPasswordHasher(BasePasswordHasher):
    """Verifies the previous Node crypto.scryptSync format for one-time migration."""
    algorithm = "legacy_node_scrypt"

    def encode(self, password, salt, n=16384, r=8, p=1):
        digest=hashlib.scrypt(password.encode("utf-8"),salt=salt.encode("utf-8"),n=n,r=r,p=p,dklen=64).hex()
        return f"{self.algorithm}${n}${r}${p}${salt}${digest}"

    def verify(self, password, encoded):
        try:
            _algorithm,n,r,p,salt,expected=encoded.split("$",5)
            actual=hashlib.scrypt(password.encode("utf-8"),salt=salt.encode("utf-8"),n=int(n),r=int(r),p=int(p),dklen=64).hex()
        except (ValueError,TypeError):
            return False
        return hmac.compare_digest(actual,expected)

    def safe_summary(self, encoded):
        return {"algorithm":self.algorithm,"work_factor":"16384 / r8 / p1","salt":"********","hash":"********"}

    def must_update(self, encoded):
        # On the first successful legacy login, Django replaces this with Argon2.
        return True
