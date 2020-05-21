"""
Minimal typing stub for Cocoa as used by objc_asyncio
"""
import typing
import typing_extensions
import enum

def CFAbsoluteTimeGetCurrent() -> float: ...

class CFRunLoopRef: ...
class CFRunLoopSourceRef: ...
class CFRunLoopObserverRef: ...
class CFRunLoopTimerRef: ...
class CFAllocatorRef: ...
class CFFileDescriptorRef: ...

class CFActivityFlags(enum.IntFlag):
    kCFRunLoopBeforeTimers = 1
    kCFRunLoopEntry = 2
    kCFRunLoopExit = 4

kCFRunLoopBeforeTimers = CFActivityFlags.kCFRunLoopBeforeTimers
kCFRunLoopEntry = CFActivityFlags.kCFRunLoopEntry
kCFRunLoopExit = CFActivityFlags.kCFRunLoopExit

class CFCallbackFlags(enum.IntFlag):
    kCFFileDescriptorReadCallBack = 1
    kCFFileDescriptorWriteCallBack = 2

kCFFileDescriptorReadCallBack = CFCallbackFlags.kCFFileDescriptorReadCallBack
kCFFileDescriptorWriteCallBack = CFCallbackFlags.kCFFileDescriptorWriteCallBack

class RunLoopMode(enum.Enum):
    kCFRunLoopCommonModes = enum.auto()

kCFRunLoopCommonModes = RunLoopMode.kCFRunLoopCommonModes

def CFRunLoopGetCurrent() -> CFRunLoopRef: ...
def CFRunLoopAddObserver(
    runloop: CFRunLoopRef, observer: CFRunLoopObserverRef, mode: RunLoopMode
) -> None: ...
def CFRunLoopAddTimer(
    runloop: CFRunLoopRef, timer: CFRunLoopTimerRef, mode: RunLoopMode
) -> None: ...
def CFRunLoopObserverCreateWithHandler(
    allocator: typing.Optional[CFAllocatorRef],
    activities: CFActivityFlags,
    repeats: bool,
    order: int,
    block: typing.Callable[[CFRunLoopObserverRef, CFActivityFlags], None],
) -> CFRunLoopObserverRef: ...
def CFRunLoopRemoveObserver(
    runloop: CFRunLoopRef, observer: CFRunLoopObserverRef, mode: RunLoopMode
): ...
def CFRunLoopRemoveTimer(
    runloop: CFRunLoopRef, timer: CFRunLoopTimerRef, mode: RunLoopMode
) -> None: ...
def CFRunLoopRun() -> None: ...
def CFRunLoopStop(runloop: CFRunLoopRef): ...
def CFRunLoopWakeUp(runloop: CFRunLoopRef): ...
def CFRunLoopTimerCreateWithHandler(
    allocator: typing.Optional[CFAllocatorRef],
    fireDate: float,
    interval: float,
    flags: typing_extensions.Literal[0],
    order: int,
    block: typing.Callable[[CFRunLoopTimerRef], None],
) -> CFRunLoopTimerRef: ...
def CFRunLoopTimerGetNextFireDate(timer: CFRunLoopTimerRef) -> float: ...
def CFRunLoopTimerInvalidate(timer: CFRunLoopTimerRef) -> None: ...
def CFRunLoopTimerSetNextFireDate(
    timer: CFRunLoopTimerRef, fireDate: float
) -> None: ...
def CFFileDescriptorCreate(
    allocator: typing.Optional[CFAllocatorRef],
    fd: int,
    closeOnInvalidate: bool,
    callout: typing.Callable[[CFFileDescriptorRef, CFCallbackFlags, typing.Any], None],
    info: typing.Any,
) -> None: ...
def CFFileDescriptorCreateRunLoopSource(
    allocator: typing.Optional[CFAllocatorRef], f: CFFileDescriptorRef, order: int
) -> CFRunLoopSourceRef: ...
def CFFileDescriptorDisableCallBacks(
    f: CFFileDescriptorRef, callBackTypes: CFCallbackFlags
) -> None: ...
def CFFileDescriptorEnableCallBacks(
    f: CFFileDescriptorRef, callBackTypes: CFCallbackFlags
) -> None: ...
def CFRunLoopAddSource(runloop: CFRunLoopRef, source: CFRunLoopSourceRef) -> None: ...
def CFRunLoopRemoveSource(
    runloop: CFRunLoopRef, source: CFRunLoopSourceRef
) -> None: ...
