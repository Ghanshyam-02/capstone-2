"""Create the RSA key pair Snowflake uses to log in the pipeline and the API.

    python -m common.create_keys

- keys/rsa_key.p8  = PRIVATE key. Stays on your laptop (git-ignored). Never share it.
- keys/rsa_key.pub = PUBLIC key. Goes into Snowflake (sql/00_setup.sql).
Prints the public key as ONE line, ready to paste into 00_setup.sql.
"""
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from common.config import PROJECT_ROOT

KEYS_DIR = PROJECT_ROOT / "keys"
private_path, public_path = KEYS_DIR / "rsa_key.p8", KEYS_DIR / "rsa_key.pub"

if private_path.exists():
    raise SystemExit(f"{private_path} already exists - delete it first if you really want a new key.")

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
private_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
public_pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo)

KEYS_DIR.mkdir(exist_ok=True)
private_path.write_bytes(private_pem)
public_path.write_bytes(public_pem)

one_line = "".join(line for line in public_pem.decode().splitlines() if "-----" not in line)
print(f"Created {private_path} and {public_path}\n")
print("Paste this into sql/00_setup.sql in place of PASTE_YOUR_PUBLIC_KEY_HERE:\n")
print(one_line)
