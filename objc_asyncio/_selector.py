"""
eventloop selector, based roughly on the
stdlib selector API

The basic idea is that the CoreFoundation
APIs are used as a selector, but that the
actual I/O will be performed using the
regular Python APIs.
"""
import enum
import typing
from collections import namedtuple
from selectors import _SelectorMapping

from Cocoa import (
    CFFileDescriptorCreate,
    CFFileDescriptorCreateRunLoopSource,
    CFFileDescriptorDisableCallBacks,
    CFFileDescriptorEnableCallBacks,
    CFRunLoopAddSource,
    CFRunLoopRemoveSource,
    kCFFileDescriptorReadCallBack,
    kCFFileDescriptorWriteCallBack,
    kCFRunLoopCommonModes,
)

SelectorKey = namedtuple(
    "SelectorKey", ["fileobj", "fd", "events", "data", "cffd", "cfsource"]
)


class Events(enum.IntFlag):
    EVENT_READ = kCFFileDescriptorReadCallBack
    EVENT_WRITE = kCFFileDescriptorWriteCallBack


EVENT_READ = Events.EVENT_READ
EVENT_WRITE = Events.EVENT_WRITE

ALL_EVENTS = EVENT_READ | EVENT_WRITE


def _valid_events(events: Events):
    return (events != 0) and ((events & ALL_EVENTS) == events)


def _fileobj_to_fd(fileobj: typing.Union[int, typing.IO]):
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

    def _callout(self, cffd, callbackTypes, info):
        key = self._fd_to_key[info]

        # CFFileDescriptor disables events once triggered, our
        # contract is that events will keep getting triggered
        # until explicitly disabled.
        self._eventloop._io_event(callbackTypes, key)
        CFFileDescriptorEnableCallBacks(key.cffd, key.events)

    def _set_events(self, cffd, old_events, new_events):
        if old_events:
            CFFileDescriptorDisableCallBacks(cffd, old_events)
        if new_events:
            CFFileDescriptorEnableCallBacks(cffd, new_events)

    def register(self, fileobj, events, data=None):
        if not _valid_events(events):
            raise ValueError(f"Invalid events: {events}")

        fd = self._fileobj_lookup(fileobj)
        if fd in self._fd_to_key:
            raise KeyError(f"{fileobj} (FD {fd}) is already registered")

        cffd = CFFileDescriptorCreate(None, fd, False, self._callout, fd)
        cfsource = CFFileDescriptorCreateRunLoopSource(None, cffd, 0)
        CFRunLoopAddSource(self._eventloop._loop, cfsource, kCFRunLoopCommonModes)

        key = SelectorKey(
            fileobj, self._fileobj_lookup(fileobj), events, data, cffd, cfsource
        )

        self._fd_to_key[key.fd] = key
        self._set_events(key.cffd, 0, events)
        return key

    def unregister(self, fileobj):
        try:
            key = self._fd_to_key.pop(self._fileobj_lookup(fileobj))
        except KeyError:
            raise KeyError(f"{fileobj} is not registered") from None

        CFRunLoopRemoveSource(
            self._eventloop._loop, key.cfsource, kCFRunLoopCommonModes
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
            self._set_events(key.cffd, key.events, events)
            key = key._replace(events=events, data=data)
            self._fd_to_key[key.fd] = key

        elif data != key.data:
            key = key._replace(data=data)
            self._fd_to_key[key.fd] = key

        self._set_events(key.cffd, key.events, 0)
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
