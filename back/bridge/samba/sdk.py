"""Typed, operation-owned boundary around the synchronous SMB SDK.

SMB structures are dynamic at this boundary. No credentials, global connection pool,
DFS referral cache or SDK exceptions are exposed to file-share consumers.
"""
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUntypedBaseClass=false
from __future__ import annotations

import time
import socket
import threading
from collections.abc import Generator, Iterator, Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, BinaryIO, Literal, cast
from uuid import uuid4

import smbclient
from smbclient._io import SMBFileTransaction, query_info, set_info
from smbprotocol.connection import Connection
from smbprotocol.exceptions import SMBAuthenticationError, SMBException, SMBResponseException
from smbprotocol.header import NtStatus, Commands
from smbprotocol.file_info import (
    FileAttributeTagInformation, FileBasicInformation, FileDispositionInformation,
    FileInternalInformation, FileStandardInformation,
)
from smbprotocol.open import CreateOptions, FilePipePrinterAccessMask
from smbprotocol.session import Session
from smbprotocol.tree import TreeConnect, ShareType, SMB2TreeConnectResponse
from .share_rpc import ShareInfo, ShareEnumerationError, list_shares

_CONNECT_SECONDS = 10
_RESPONSE_SECONDS = 30
_OPERATION_SECONDS = 300
# MS-ERREF STATUS_MEDIA_WRITE_PROTECTED; absent from smbprotocol's NtStatus subset.
_STATUS_MEDIA_WRITE_PROTECTED = 0xC00000A2


class _SmbOperationError(OSError):
    """A sanitized SDK diagnostic which must survive nested boundaries."""


@dataclass(frozen=True)
class Metadata:
    size: int
    inode: int
    modified_ns: int
    changed_ns: int
    attributes: int


@contextmanager
def _errors() -> Generator[None]:
    try:
        yield
    except SMBAuthenticationError:
        raise PermissionError("SMB authentication failed.") from None
    except ShareEnumerationError:
        raise
    except OSError as exc:
        if getattr(exc, "ntstatus", None) == NtStatus.STATUS_BAD_NETWORK_NAME:
            raise FileNotFoundError("SMB share was not found.") from None
        # smbclient does not map ACCESS_DENIED to POSIX errno.
        if getattr(exc, "ntstatus", None) in {
            NtStatus.STATUS_ACCESS_DENIED,
            NtStatus.STATUS_PRIVILEGE_NOT_HELD, NtStatus.STATUS_LOGON_FAILURE, _STATUS_MEDIA_WRITE_PROTECTED,
        }:
            raise PermissionError("SMB denied the file operation.") from None
        if isinstance(exc, (FileNotFoundError, FileExistsError, PermissionError,
                            IsADirectoryError, NotADirectoryError, _SmbOperationError)):
            raise
        if isinstance(exc, TimeoutError):
            raise TimeoutError("SMB operation timed out.") from None
        if exc.errno == 2:
            raise FileNotFoundError("SMB resource was not found.") from None
        if exc.errno == 17:
            raise FileExistsError("SMB destination already exists.") from None
        if exc.errno in {1, 13, 30}:
            raise PermissionError("SMB denied the file operation.") from None
        if exc.errno == 20:
            raise NotADirectoryError("SMB parent is not a directory.") from None
        if exc.errno == 21:
            raise IsADirectoryError("SMB operation requires a file.") from None
        status = getattr(exc, "ntstatus", None)
        code = f"0x{status:08x}" if isinstance(status, int) else str(exc.errno)
        raise _SmbOperationError(f"SMB file operation failed (status {code}); check the share before retrying a mutation.") from None
    except SMBResponseException as exc:
        if exc.status == NtStatus.STATUS_BAD_NETWORK_NAME:
            raise FileNotFoundError("SMB share was not found.") from None
        if exc.status in {NtStatus.STATUS_ACCESS_DENIED, NtStatus.STATUS_PRIVILEGE_NOT_HELD,
                          NtStatus.STATUS_LOGON_FAILURE, _STATUS_MEDIA_WRITE_PROTECTED}:
            raise PermissionError("SMB authentication or file access was denied.") from None
        raise _SmbOperationError("SMB server refused the operation; check the share before retrying a mutation.") from None
    except SMBException:
        raise ConnectionError("SMB connection failed or closed; check the share before retrying a mutation.") from None


def _translate[**P, T](operation: Callable[P, T]) -> Callable[P, T]:
    def translated(*args: P.args, **kwargs: P.kwargs) -> T:
        with _errors():
            return operation(*args, **kwargs)
    return translated


class _Connection(Connection):
    def __init__(self, server: str, port: int) -> None:
        super().__init__(uuid4(), server, port, require_signing=True)
        self.deadline = time.monotonic() + _OPERATION_SECONDS
        self.share_types: dict[int, int] = {}

    def receive(self, request: Any, wait: bool = True, timeout: float | None = None,
                resolve_symlinks: bool = True) -> Any:
        del resolve_symlinks
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("SMB operation timed out.")
        # Disable the SDK's automatic symlink traversal and bound every response.
        response = super().receive(request, wait=wait,
                                   timeout=min(timeout or _RESPONSE_SECONDS, _RESPONSE_SECONDS, remaining),
                                   resolve_symlinks=False)
        # TreeConnect does not retain share_type. Capture the negotiated type
        # from its response so file operations can reject non-disk endpoints.
        if response is not None and response["command"].get_value() == Commands.SMB2_TREE_CONNECT:
            tree = SMB2TreeConnectResponse()
            tree.unpack(response["data"].get_value())
            self.share_types[int(response["tree_id"].get_value())] = int(tree["share_type"].get_value())
        return response


class SmbSession:
    """One independent, signed SMB connection, closed with its owning operation."""

    def __init__(self, server: str, port: int, share: str, username: str,
                 password: str, encrypt: bool) -> None:
        self.connection = _Connection(server, port)
        self.watchdog: threading.Timer | None = None
        self.smb_session: Session | None = None
        self.connected_shares: dict[str, int] = {}
        self.root = f"\\\\{server}\\{share}"
        self.kwargs: dict[str, Any] = {
            "username": username, "password": password, "port": port,
            "encrypt": encrypt, "auth_protocol": "ntlm", "connection_timeout": _CONNECT_SECONDS,
            "connection_cache": {f"{server.lower()}:{port}": self.connection},
        }

    def __enter__(self) -> SmbSession:
        try:
            # Shutdown bypasses the SDK send lock so even a blocked TCP send wakes up.
            self.watchdog = threading.Timer(_OPERATION_SECONDS, self._interrupt)
            self.watchdog.daemon = True
            self.watchdog.start()
            self.connection.connect(timeout=_CONNECT_SECONDS)
            session = Session(self.connection, username=self.kwargs["username"],
                              password=self.kwargs["password"],
                              require_encryption=self.kwargs["encrypt"], auth_protocol="ntlm")
            session.connect()
            self.smb_session = session
            tree = TreeConnect(session, self.root)
            tree.connect()
            if tree.is_dfs_share:
                raise ValueError("DFS shares are unsupported; configure the final SMB share.")
            self.connected_shares[self.root.casefold()] = self.connection.share_types[cast(int, tree.tree_connect_id)]
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args: object) -> None:
        if self.watchdog is not None:
            self.watchdog.cancel()
            self.watchdog.join(timeout=1)
        # Closing the socket also releases handles after a broken/expired session.
        self.connection.disconnect(close=False, timeout=5)

    def _interrupt(self) -> None:
        transport = cast(Any, self.connection.transport)
        peer = getattr(transport, "_sock", None)
        if peer is not None:
            try:
                peer.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    @_translate
    def connect_share(self, root: str) -> None:
        if root.casefold() in self.connected_shares:
            if self.connected_shares[root.casefold()] != ShareType.SMB2_SHARE_TYPE_DISK:
                raise PermissionError("Only disk shares can be accessed as file resources.")
            return
        if self.smb_session is None:
            raise ConnectionError("SMB session is closed.")
        tree = TreeConnect(self.smb_session, root)
        tree.connect()
        kind = self.connection.share_types[cast(int, tree.tree_connect_id)]
        if kind != ShareType.SMB2_SHARE_TYPE_DISK:
            tree.disconnect()
            raise PermissionError("Only disk shares can be accessed as file resources.")
        if tree.is_dfs_share:
            tree.disconnect()
            raise ValueError("DFS shares are unsupported; configure the final SMB share.")
        self.connected_shares[root.casefold()] = kind

    @_translate
    def shares(self) -> list[ShareInfo]:
        with smbclient.open_file(self.root + "\\srvsvc", mode="r+b", buffering=0,
                                 file_type="pipe", **self.kwargs) as pipe:
            return list_shares(cast(BinaryIO, pipe), self.connection.server_name)

    @staticmethod
    def _metadata(raw: Any) -> Metadata:
        with SMBFileTransaction(raw) as transaction:
            query_info(transaction, FileBasicInformation)
            query_info(transaction, FileInternalInformation)
            query_info(transaction, FileStandardInformation)
            query_info(transaction, FileAttributeTagInformation)
        basic, internal, standard, attributes = cast(tuple[Any, Any, Any, Any], transaction.results)
        return Metadata(int(standard["end_of_file"].get_value()),
                        int(internal["index_number"].get_value()),
                        int(basic["last_write_time"].get_value()),
                        int(basic["change_time"].get_value()),
                        int(attributes["file_attributes"].get_value()))

    @_translate
    def stat(self, path: str) -> Metadata:
        # SMBRawIO (rather than SMBFileIO) permits both directories and files.
        from smbclient._io import SMBRawIO
        raw = SMBRawIO(path, mode="r", desired_access=FilePipePrinterAccessMask.FILE_READ_ATTRIBUTES,
                       share_access="rwd", create_options=CreateOptions.FILE_OPEN_REPARSE_POINT,
                       **self.kwargs)
        return self._metadata(raw)

    @contextmanager
    def open(self, path: str, mode: Literal["rb", "r+b", "x+b"], *, delete: bool = False) -> Generator[BinaryIO]:
        options: dict[str, Any] = dict(self.kwargs)
        options["create_options"] = CreateOptions.FILE_OPEN_REPARSE_POINT
        if delete:
            options["desired_access"] = FilePipePrinterAccessMask.GENERIC_READ | FilePipePrinterAccessMask.DELETE
        elif mode == "x+b":
            options["desired_access"] = (FilePipePrinterAccessMask.GENERIC_READ
                                         | FilePipePrinterAccessMask.GENERIC_WRITE
                                         | FilePipePrinterAccessMask.DELETE)
        with _errors(), smbclient.open_file(path, mode=mode, buffering=0,
                                 share_access="r" if mode == "rb" and not delete else "",
                                 **options) as raw:
            yield cast(BinaryIO, raw)

    @_translate
    def fstat(self, handle: BinaryIO) -> Metadata:
        return self._metadata(handle)

    @_translate
    def delete_handle(self, handle: BinaryIO) -> None:
        info = FileDispositionInformation()
        info["delete_pending"] = True
        with SMBFileTransaction(handle) as transaction:
            set_info(transaction, info)

    def children(self, path: str) -> Iterator[str]:
        with _errors():
            for entry in smbclient.scandir(path, **self.kwargs):
                yield str(entry.name)

    @_translate
    def mkdir(self, path: str) -> None:
        smbclient.mkdir(path, **self.kwargs)

    @_translate
    def rmdir(self, path: str) -> None:
        smbclient.rmdir(path, **self.kwargs)

    @_translate
    def rename(self, source: str, destination: str, overwrite: bool) -> None:
        operation = smbclient.replace if overwrite else smbclient.rename
        operation(source, destination, **self.kwargs)


@contextmanager
def session(server: str, port: int, share: str, username: str,
            password: str, encrypt: bool) -> Generator[SmbSession]:
    with _errors(), SmbSession(server, port, share, username, password, encrypt) as active:
        yield active
