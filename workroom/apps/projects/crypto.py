"""Encrypt project AI keys.

Server mode uses ``cryptography.Fernet`` with a version prefix and an explicit
``WORKROOM_ENCRYPTION_KEY``. Local mode keeps the original Windows DPAPI
storage. The plaintext key is never written to the database, logs or templates.

Fernet ciphertext is portable across operating systems *when the same key is
provided*. Old ``dpapi:v1:`` ciphertext is tied to a Windows user and cannot be
read on Linux; those rows are left untouched and the UI asks the owner to fill
the key again (or to migrate explicitly on Windows).
"""

from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes

from django.conf import settings

DPAPI_PREFIX = 'dpapi:v1:'
FERNET_PREFIX = 'fernet:v1:'
# Backwards-compatible alias used by older local tests.
PREFIX = DPAPI_PREFIX
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class CryptoError(Exception):
    """Raised when a key cannot be encrypted or decrypted."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


if sys.platform == 'win32':
    class _Blob(ctypes.Structure):
        _fields_ = [
            ('cbData', wintypes.DWORD),
            ('pbData', ctypes.POINTER(ctypes.c_char)),
        ]

    _crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_Blob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_Blob),
    ]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_Blob),
        ctypes.c_void_p,
        ctypes.POINTER(_Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_Blob),
    ]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL

    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p

    def _to_blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
        buffer = ctypes.create_string_buffer(data, len(data))
        return (
            _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))),
            buffer,
        )

    def _call(function, data: bytes) -> bytes:
        blob_in, _keep = _to_blob(data)
        blob_out = _Blob()
        ok = function(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(blob_out),
        )
        if not ok:
            raise CryptoError(
                f'系统加密调用失败（错误码 {ctypes.get_last_error()}）。'
            )
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


def _is_server() -> bool:
    return getattr(settings, 'WORKROOM_MODE', 'local') == 'server'


def _fernet():
    from cryptography.fernet import Fernet

    key = (getattr(settings, 'WORKROOM_ENCRYPTION_KEY', '') or '').strip()
    if not key:
        raise CryptoError('服务器缺少 WORKROOM_ENCRYPTION_KEY，无法读写 Key。')
    try:
        return Fernet(key.encode('ascii'))
    except Exception as exc:  # noqa: BLE001 - invalid key is a config error
        raise CryptoError('WORKROOM_ENCRYPTION_KEY 无效，请检查服务器配置。') from exc


def available() -> bool:
    if _is_server():
        return bool(getattr(settings, 'WORKROOM_ENCRYPTION_KEY', ''))
    return sys.platform == 'win32'


def protect(plaintext: str) -> str:
    """Return a portable string token for ``plaintext`` (empty stays empty)."""
    if not plaintext:
        return ''
    if _is_server():
        token = _fernet().encrypt(plaintext.encode('utf-8'))
        return FERNET_PREFIX + token.decode('ascii')
    if not available():
        raise CryptoError('当前系统不支持本机加密存储，请在 Windows 上配置 AI Key。')
    sealed = _call(_crypt32.CryptProtectData, plaintext.encode('utf-8'))
    return DPAPI_PREFIX + base64.b64encode(sealed).decode('ascii')


def unprotect(token: str) -> str:
    """Return the plaintext for a token produced by :func:`protect`."""
    if not token:
        return ''
    if token.startswith(FERNET_PREFIX):
        try:
            return _fernet().decrypt(
                token[len(FERNET_PREFIX):].encode('ascii')
            ).decode('utf-8')
        except CryptoError:
            raise
        except Exception as exc:  # noqa: BLE001 - wrong key / corrupt token
            raise CryptoError(
                'Key 解密失败：WORKROOM_ENCRYPTION_KEY 与密文不匹配，或密文已损坏。'
            ) from exc
    if not token.startswith(DPAPI_PREFIX):
        raise CryptoError('Key 的存储格式无法识别，请重新填写。')
    if sys.platform != 'win32':
        raise CryptoError(
            '这是旧 Windows 本机 DPAPI 密文，Linux 服务器无法解密；'
            '请在服务器上重新填写该 AI 的 Key（旧密文不会被清空）。'
        )
    try:
        sealed = base64.b64decode(token[len(DPAPI_PREFIX):], validate=True)
    except (ValueError, TypeError) as exc:
        raise CryptoError('Key 内容已损坏，请重新填写。') from exc
    try:
        return _call(_crypt32.CryptUnprotectData, sealed).decode('utf-8')
    except CryptoError as exc:
        raise CryptoError(
            'Key 解密失败：可能换了 Windows 账号或机器，请重新填写。'
        ) from exc
    except UnicodeDecodeError as exc:
        raise CryptoError('Key 内容已损坏，请重新填写。') from exc
