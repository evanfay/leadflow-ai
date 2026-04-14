import os

_fernet_instance = None


def get_fernet():
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    from cryptography.fernet import Fernet
    key = os.environ.get('ENCRYPTION_KEY')
    if not key:
        new_key = Fernet.generate_key()
        print(f'\n[WARNING] ENCRYPTION_KEY not set. Using ephemeral key for dev.')
        print(f'[WARNING] Set ENCRYPTION_KEY={new_key.decode()} in your .env for persistence.\n')
        _fernet_instance = Fernet(new_key)
    else:
        if isinstance(key, str):
            key = key.encode()
        _fernet_instance = Fernet(key)

    return _fernet_instance


def encrypt(value: str) -> str:
    if not value:
        return ''
    return get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value:
        return ''
    try:
        return get_fernet().decrypt(value.encode()).decode()
    except Exception:
        return ''
