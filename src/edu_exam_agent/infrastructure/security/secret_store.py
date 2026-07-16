"""Windows DPAPI encrypted local secret storage."""

from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


class SecretStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def set(self, name: str, value: str) -> None:
        if os.name != "nt":
            raise RuntimeError("安全密钥存储仅支持 Windows")
        source, buffer = _blob(value.encode())
        output = _DataBlob()
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(source), "EduExamAgent", None, None, None, 0, ctypes.byref(output)
        ):
            raise ctypes.WinError()
        try:
            encrypted = ctypes.string_at(output.pbData, output.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output.pbData)
            del buffer
        values = self._read_all()
        values[name] = base64.b64encode(encrypted).decode("ascii")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(values), encoding="utf-8")

    def get(self, name: str) -> str | None:
        encoded = self._read_all().get(name)
        if not encoded:
            return None
        source, buffer = _blob(base64.b64decode(encoded))
        output = _DataBlob()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData).decode()
        finally:
            ctypes.windll.kernel32.LocalFree(output.pbData)
            del buffer

    def has(self, name: str) -> bool:
        return bool(self._read_all().get(name))

    def _read_all(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        value = json.loads(self._path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
