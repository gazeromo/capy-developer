"""Local credentials through public Security.framework APIs or POSIX private files.

No shell commands, process environment or subprocess arguments carry secrets.
The file fallback is qualified only on POSIX. Tests may explicitly inject the
file backend into test-owned roots on any platform; that is not Windows support.
"""
from __future__ import annotations

import ctypes
import os
import platform
import re

from ..errors import DeveloperError


class FileCredentials:
    """Values reside only in State's owner-only SQLite file/private directory."""
    mechanism = 'private-local-file'
    def __init__(self, *, test_owned: bool = False):
        if os.name != 'posix' and not test_owned:
            raise DeveloperError('CREDENTIAL_STORE_UNAVAILABLE', 'this platform has no qualified protected credential store')

    def store(self, account: str, secret: str) -> str:
        return secret

    def read(self, value: str) -> str:
        if value.startswith('keychain:'):
            raise DeveloperError('CREDENTIAL_STORE_UNAVAILABLE', 'this credential requires its original macOS Keychain')
        return value

    def remove(self, value: str) -> None:
        pass


class KeychainCredentials:
    """macOS generic-password items, addressed by opaque installation identity."""
    mechanism = 'macos-keychain'
    service = 'local.capy.developer.link.v0'
    prefix = 'keychain:'

    def __init__(self):
        self.cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.security = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
        pointer = ctypes.c_void_p
        self.cf.CFStringCreateWithCString.argtypes = [pointer, ctypes.c_char_p, ctypes.c_uint32]
        self.cf.CFStringCreateWithCString.restype = pointer
        self.cf.CFDataCreate.argtypes = [pointer, ctypes.c_void_p, ctypes.c_long]
        self.cf.CFDataCreate.restype = pointer
        self.cf.CFDictionaryCreate.argtypes = [pointer, pointer, pointer, ctypes.c_long, pointer, pointer]
        self.cf.CFDictionaryCreate.restype = pointer
        self.cf.CFDataGetLength.argtypes = [pointer]
        self.cf.CFDataGetLength.restype = ctypes.c_long
        self.cf.CFDataGetBytePtr.argtypes = [pointer]
        self.cf.CFDataGetBytePtr.restype = pointer
        self.cf.CFGetTypeID.argtypes = [pointer]
        self.cf.CFGetTypeID.restype = ctypes.c_ulong
        self.cf.CFDataGetTypeID.restype = ctypes.c_ulong
        self.cf.CFRelease.argtypes = [pointer]
        self.security.SecItemAdd.argtypes = [pointer, ctypes.POINTER(pointer)]
        self.security.SecItemAdd.restype = ctypes.c_int32
        self.security.SecItemCopyMatching.argtypes = [pointer, ctypes.POINTER(pointer)]
        self.security.SecItemCopyMatching.restype = ctypes.c_int32
        self.security.SecItemDelete.argtypes = [pointer]
        self.security.SecItemDelete.restype = ctypes.c_int32

    def _constant(self, name):
        return ctypes.c_void_p.in_dll(self.security, name).value

    def _query(self, account: str, *, secret: str | None = None, returning: bool = False):
        if re.fullmatch(r'[0-9a-f]{32}', account) is None:
            raise DeveloperError('CREDENTIAL_REFERENCE_INVALID', 'credential reference is invalid')
        allocations = []
        pairs = [(self._constant('kSecClass'), self._constant('kSecClassGenericPassword'))]
        for name, value in [('kSecAttrService', self.service), ('kSecAttrAccount', account)]:
            ref = self.cf.CFStringCreateWithCString(None, value.encode(), 0x08000100)
            allocations.append(ref)
            pairs.append((self._constant(name), ref))
        if secret is not None:
            encoded = secret.encode('ascii')
            buffer = ctypes.create_string_buffer(encoded)
            ref = self.cf.CFDataCreate(None, buffer, len(encoded))
            allocations.append(ref)
            pairs.append((self._constant('kSecValueData'), ref))
        if returning:
            pairs.append((self._constant('kSecReturnData'), ctypes.c_void_p.in_dll(self.cf, 'kCFBooleanTrue').value))
            pairs.append((self._constant('kSecMatchLimit'), self._constant('kSecMatchLimitOne')))
        keys = (ctypes.c_void_p * len(pairs))(*(key for key, _ in pairs))
        values = (ctypes.c_void_p * len(pairs))(*(value for _, value in pairs))
        # Null callbacks keep our explicitly owned refs alive until the operation ends.
        query = self.cf.CFDictionaryCreate(None, keys, values, len(pairs), None, None)
        allocations.append(query)
        if not all(allocations):
            self._release(allocations)
            raise DeveloperError('CREDENTIAL_STORE_UNAVAILABLE', 'macOS Keychain query allocation failed')
        return query, allocations

    def _release(self, allocations):
        for item in reversed(allocations):
            if item:
                self.cf.CFRelease(item)

    @staticmethod
    def _success(status: int):
        if status != 0:
            # OS status only; never include query attributes or secret values.
            raise DeveloperError('CREDENTIAL_STORE_REJECTED', 'macOS Keychain did not permit this credential operation')

    def store(self, account: str, secret: str) -> str:
        query, allocations = self._query(account, secret=secret)
        try:
            self._success(self.security.SecItemAdd(query, None))
        finally:
            self._release(allocations)
        return self.prefix + account

    def read(self, value: str) -> str:
        if not value.startswith(self.prefix):
            # Additive compatibility for previously qualified POSIX private-file rows.
            return value
        query, allocations = self._query(value[len(self.prefix):], returning=True)
        result = ctypes.c_void_p()
        try:
            self._success(self.security.SecItemCopyMatching(query, ctypes.byref(result)))
            if not result.value or self.cf.CFGetTypeID(result) != self.cf.CFDataGetTypeID() or self.cf.CFDataGetLength(result) != 64:
                raise DeveloperError('CREDENTIAL_STORE_INVALID', 'saved developer credential is invalid')
            raw = ctypes.string_at(self.cf.CFDataGetBytePtr(result), 64)
            if re.fullmatch(rb'[0-9a-f]{64}', raw) is None:
                raise DeveloperError('CREDENTIAL_STORE_INVALID', 'saved developer credential is invalid')
            return raw.decode('ascii')
        finally:
            if result.value:
                self.cf.CFRelease(result)
            self._release(allocations)

    def remove(self, value: str) -> None:
        if not value.startswith(self.prefix):
            return
        query, allocations = self._query(value[len(self.prefix):])
        try:
            status = self.security.SecItemDelete(query)
            if status != -25300:  # Already absent is idempotent removal.
                self._success(status)
        finally:
            self._release(allocations)


def default_credentials():
    if platform.system() == 'Darwin':
        try:
            return KeychainCredentials()
        except (OSError, AttributeError, ValueError):
            # Only API unavailability permits fallback. User denial never does.
            result = FileCredentials()
            result.fallback_reason = 'Public Security.framework APIs could not be loaded.'
            return result
    return FileCredentials()
