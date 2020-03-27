"""
eventloop selector, based roughly on the
stdlib selector API

The basic idea is that the CoreFoundation
APIs are used as a selector, but that the
actual I/O will be performed using the
regular Python APIs.
"""
from collections import namedtuple
from selectors import _SelectorMapping

from Cocoa import (
    CFRunLoopAddSource,
    CFRunLoopRemoveSource,
    CFSocketCreateRunLoopSource,
    CFSocketCreateWithNative,
    CFSocketDisableCallBacks,
    kCFRunLoopCommonModes,
    kCFSocketNoCallBack,
)

SelectorKey = namedtuple(
    "SelectorKey", ["fileobj", "fd", "events", "data", "cfsocket", "cfsource"]
)


def _valid_events(events):
    # XXX
    return True


def _fileobj_to_fd(fileobj):
    if isinstance(fileobj, int):
        fd = fileobj
    else:
        try:
            fd = int(fileobj.fileno())
        except (AttributeError, TypeError, ValueError):
            raise ValueError(f"Invalid file object: {fileobj}") from None
    if fd < 0:
        raise ValueError("fInvalid file descriptor: {fd}")
    return fd


class RunLoopSelector:
    def __init__(self, eventloop):
        self._eventloop = eventloop
        self._map = _SelectorMapping(self)
        self._fd_to_key = {}

    def close(self):
        # unregister all
        for key in list(self._fd_to_key.values()):
            self.unregister(key.fileobj)

        self._fd_to_key.clear()
        self._map = None
        self._eventloop = None

    def _fileobj_lookup(self, fileobj):
        try:
            return _fileobj_to_fd(fileobj)
        except ValueError:
            # Do an exhaustive search.
            for key in self._fd_to_key.values():
                if key.fileobj is fileobj:
                    return key.fd
            # Raise ValueError after all.
            raise

    def _callout(self, cfsock, event, address, data, fd):
        self._eventloop._io_event(event, self._fd_to_key[fd])

    def _set_events(self, cfsock, old_events, new_events):
        CFSocketDisableCallBacks(old_events)
        CFSocketDisableCallBacks(new_events)

    def register(self, fileobj, events, data=None):
        if _valid_events(events):
            raise ValueError(f"Invalid events: {events}")

        fd = self._fileobj_lookup(fileobj)
        if fd in self._fd_to_key:
            raise KeyError(f"{fileobj} (FD {fd}) is already registered")

        cfsock = CFSocketCreateWithNative(
            None, fd, kCFSocketNoCallBack, self._callout, fd
        )
        cfsource = CFSocketCreateRunLoopSource(None, cfsock, 0)
        CFRunLoopAddSource(self._eventloop._runloop, cfsource, kCFRunLoopCommonModes)

        key = SelectorKey(
            fileobj, self._fileobj_lookup(fileobj), events, data, cfsock, cfsource
        )

        self._fd_to_key[key.fd] = key
        self._set_events(key.cfsocket, kCFSocketNoCallBack, events)
        return key

    def unregister(self, fileobj):
        try:
            key = self._fd_to_key.pop(self._fileobj_lookup(fileobj))
        except KeyError:
            raise KeyError(f"{fileobj} is not registered") from None

        CFRunLoopRemoveSource(
            self._eventloop._runloop, key.cfsource, kCFRunLoopCommonModes
        )
        return key

    def modify(self, fileobj, events, data=None):
        try:
            key = self._fd_to_key[self._fileobj_lookup(fileobj)]
        except KeyError:
            raise KeyError("{fileobj} is not registered") from None

        if not _valid_events(events):
            raise ValueError(f"Invalid events: {events}")

        if events != key.events:
            self._set_events(key.cfsocket, key.events, events)
            key = key._replace(events=events, data=data)
            self._fd_to_key[key.fd] = key

        elif data != key.data:
            key = key._replace(data=data)
            self._fd_to_key[key.fd] = key

        return key

    def get_key(self, fileobj):
        if self._map is None:
            raise RuntimeError(f"Selector is closed")
        try:
            return self._map[fileobj]
        except KeyError:
            raise KeyError(f"{fileobj} is not registered") from None

    def get_map(self):
        return self._map
