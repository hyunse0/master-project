import os

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    key = os.environ.get("APP_SECRET_KEY")
    if not key:
        raise RuntimeError(
            "APP_SECRET_KEY가 설정되지 않았습니다 — domain_connections의 비밀번호를 "
            "암복호화할 수 없습니다. .env.example의 안내대로 키를 생성해 .env에 채우세요."
        )
    return Fernet(key.encode())


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt_secret(ciphertext: bytes) -> str:
    return _fernet().decrypt(bytes(ciphertext)).decode()
