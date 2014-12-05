#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012 Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Module implementing the Ganeti locking code."""

# pylint: disable=W0212

# W0212 since e.g. LockSet methods use (a lot) the internals of
# SharedLock

import os
import select
import threading
import errno
import logging
import heapq
import time

from ganeti import errors
from ganeti import utils
from ganeti import compat
from ganeti import query


_EXCLUSIVE_TEXT = "exclusive"
_SHARED_TEXT = "shared"
_DELETED_TEXT = "deleted"

_DEFAULT_PRIORITY = 0

#: Minimum timeout required to consider scheduling a pending acquisition
#: (seconds)
_LOCK_ACQUIRE_MIN_TIMEOUT = (1.0 / 1000)


def ssynchronized(mylock, shared=0):
  """Shared Synchronization decorator.

  Calls the function holding the given lock, either in exclusive or shared
  mode. It requires the passed lock to be a SharedLock (or support its
  semantics).

  @type mylock: lockable object or string
  @param mylock: lock to acquire or class member name of the lock to acquire

  """
  def wrap(fn):
    def sync_function(*args, **kwargs):
      if isinstance(mylock, basestring):
        assert args, "cannot ssynchronize on non-class method: self not found"
        # args[0] is "self"
        lock = getattr(args[0], mylock)
      else:
        lock = mylock
      lock.acquire(shared=shared)
      try:
        return fn(*args, **kwargs)
      finally:
        lock.release()
    return sync_function
  return wrap


class _SingleNotifyPipeConditionWaiter(object):
  """Helper class for SingleNotifyPipeCondition

  """
  __slots__ = [
    "_fd",
    ]

  def __init__(self, fd):
    """Constructor for _SingleNotifyPipeConditionWaiter

    @type fd: int
    @param fd: File descriptor to wait for

    """
    object.__init__(self)
    self._fd = fd

  def __call__(self, timeout):
    """Wait for something to happen on the pipe.

    @type timeout: float or None
    @param timeout: Timeout for waiting (can be None)

    """
    running_timeout = utils.RunningTimeout(timeout, True)
    poller = select.poll()
    poller.register(self._fd, select.POLLHUP)

    while True:
      remaining_time = running_timeout.Remaining()

      if remaining_time is not None:
        if remaining_time < 0.0:
          break

        # Our calculation uses seconds, poll() wants milliseconds
        remaining_time *= 1000

      try:
        result = poller.poll(remaining_time)
      except EnvironmentError, err:
        if err.errno != errno.EINTR:
          raise
        result = None

      # Check whether we were notified
      if result and result[0][0] == self._fd:
        break


class _BaseCondition(object):
  """Base class containing common code for conditions.

  Some of this code is taken from python's threading module.

  """
  __slots__ = [
    "_lock",
    "acquire",
    "release",
    "_is_owned",
    "_acquire_restore",
    "_release_save",
    ]

  def __init__(self, lock):
    """Constructor for _BaseCondition.

    @type lock: threading.Lock
    @param lock: condition base lock

    """
    object.__init__(self)

    try:
      self._release_save = lock._release_save
    except AttributeError:
      self._release_save = self._base_release_save
    try:
      self._acquire_restore = lock._acquire_restore
    except AttributeError:
      self._acquire_restore = self._base_acquire_restore
    try:
      self._is_owned = lock.is_owned
    except AttributeError:
      self._is_owned = self._base_is_owned

    self._lock = lock

    # Export the lock's acquire() and release() methods
    self.acquire = lock.acquire
    self.release = lock.release

  def _base_is_owned(self):
    """Check whether lock is owned by current thread.

    """
    if self._lock.acquire(0):
      self._lock.release()
      return False
    return True

  def _base_release_save(self):
    self._lock.release()

  def _base_acquire_restore(self, _):
    self._lock.acquire()

  def _check_owned(self):
    """Raise an exception if the current thread doesn't own the lock.

    """
    if not self._is_owned():
      raise RuntimeError("cannot work with un-aquired lock")


class SingleNotifyPipeCondition(_BaseCondition):
  """Condition which can only be notified once.

  This condition class uses pipes and poll, internally, to be able to wait for
  notification with a timeout, without resorting to polling. It is almost
  compatible with Python's threading.Condition, with the following differences:
    - notifyAll can only be called once, and no wait can happen after that
    - notify is not supported, only notifyAll

  """

  __slots__ = [
    "_read_fd",
    "_write_fd",
    "_nwaiters",
    "_notified",
    ]

  _waiter_class = _SingleNotifyPipeConditionWaiter

  def __init__(self, lock):
    """Constructor for SingleNotifyPipeCondition

    """
    _BaseCondition.__init__(self, lock)
    self._nwaiters = 0
    self._notified = False
    self._read_fd = None
    self._write_fd = None

  def _check_unnotified(self):
    """Throws an exception if already notified.

    """
    if self._notified:
      raise RuntimeError("cannot use already notified condition")

  def _Cleanup(self):
    """Cleanup open file descriptors, if any.

    """
    if self._read_fd is not None:
      os.close(self._read_fd)
      self._read_fd = None

    if self._write_fd is not None:
      os.close(self._write_fd)
      self._write_fd = None

  def wait(self, timeout):
    """Wait for a notification.

    @type timeout: float or None
    @param timeout: Waiting timeout (can be None)

    """
    self._check_owned()
    self._check_unnotified()

    self._nwaiters += 1
    try:
      if self._read_fd is None:
        (self._read_fd, self._write_fd) = os.pipe()

      wait_fn = self._waiter_class(self._read_fd)
      state = self._release_save()
      try:
        # Wait for notification
        wait_fn(timeout)
      finally:
        # Re-acquire lock
        self._acquire_restore(state)
    finally:
      self._nwaiters -= 1
      if self._nwaiters == 0:
        self._Cleanup()

  def notifyAll(self): # pylint: disable=C0103
    """Close the writing side of the pipe to notify all waiters.

    """
    self._check_owned()
    self._check_unnotified()
    self._notified = True
    if self._write_fd is not None:
      os.close(self._write_fd)
      self._write_fd = None


class PipeCondition(_BaseCondition):
  """Group-only non-polling condition with counters.

  This condition class uses pipes and poll, internally, to be able to wait for
  notification with a timeout, without resorting to polling. It is almost
  compatible with Python's threading.Condition, but only supports notifyAll and
  non-recursive locks. As an additional features it's able to report whether
  there are any waiting threads.

  """
  __slots__ = [
    "_waiters",
    "_single_condition",
    ]

  _single_condition_class = SingleNotifyPipeCondition

  def __init__(self, lock):
    """Initializes this class.

    """
    _BaseCondition.__init__(self, lock)
    self._waiters = set()
    self._single_condition = self._single_condition_class(self._lock)

  def wait(self, timeout):
    """Wait for a notification.

    @type timeout: float or None
    @param timeout: Waiting timeout (can be None)

    """
    self._check_owned()

    # Keep local reference to the pipe. It could be replaced by another thread
    # notifying while we're waiting.
    cond = self._single_condition

    self._waiters.add(threading.currentThread())
    try:
      cond.wait(timeout)
    finally:
      self._check_owned()
      self._waiters.remove(threading.currentThread())

  def notifyAll(self): # pylint: disable=C0103
    """Notify all currently waiting threads.

    """
    self._check_owned()
    self._single_condition.notifyAll()
    self._single_condition = self._single_condition_class(self._lock)

  def get_waiting(self):
    """Returns a list of all waiting threads.

    """
    self._check_owned()

    return self._waiters

  def has_waiting(self):
    """Returns whether there are active waiters.

    """
    self._check_owned()

    return bool(self._waiters)

  def __repr__(self):
    return ("<%s.%s waiters=%s at %#x>" %
            (self.__class__.__module__, self.__class__.__name__,
             self._waiters, id(self)))


class _PipeConditionWithMode(PipeCondition):
  __slots__ = [
    "shared",
    ]

  def __init__(self, lock, shared):
    """Initializes this class.

    """
    self.shared = shared
    PipeCondition.__init__(self, lock)


class SharedLock(object):
  """Implements a shared lock.

  Multiple threads can acquire the lock in a shared way by calling
  C{acquire(shared=1)}. In order to acquire the lock in an exclusive way
  threads can call C{acquire(shared=0)}.

  Notes on data structures: C{__pending} contains a priority queue (heapq) of
  all pending acquires: C{[(priority1: prioqueue1), (priority2: prioqueue2),
  ...]}. Each per-priority queue contains a normal in-order list of conditions
  to be notified when the lock can be acquired. Shared locks are grouped
  together by priority and the condition for them is stored in
  C{__pending_shared} if it already exists. C{__pending_by_prio} keeps
  references for the per-priority queues indexed by priority for faster access.

  @type name: string
  @ivar name: the name of the lock

  """
  __slots__ = [
    "__weakref__",
    "__deleted",
    "__exc",
    "__lock",
    "__pending",
    "__pending_by_prio",
    "__pending_shared",
    "__shr",
    "__time_fn",
    "name",
    ]

  __condition_class = _PipeConditionWithMode

  def __init__(self, name, monitor=None, _time_fn=time.time):
    """Construct a new SharedLock.

    @param name: the name of the lock
    @param monitor: Lock monitor with which to register

    """
    object.__init__(self)

    self.name = name

    # Used for unittesting
    self.__time_fn = _time_fn

    # Internal lock
    self.__lock = threading.Lock()

    # Queue containing waiting acquires
    self.__pending = []
    self.__pending_by_prio = {}
    self.__pending_shared = {}

    # Current lock holders
    self.__shr = set()
    self.__exc = None

    # is this lock in the deleted state?
    self.__deleted = False

    # Register with lock monitor
    if monitor:
      logging.debug("Adding lock %s to monitor", name)
      monitor.RegisterLock(self)

  def __repr__(self):
    return ("<%s.%s name=%s at %#x>" %
            (self.__class__.__module__, self.__class__.__name__,
             self.name, id(self)))

  def GetLockInfo(self, requested):
    """Retrieves information for querying locks.

    @type requested: set
    @param requested: Requested information, see C{query.LQ_*}

    """
    self.__lock.acquire()
    try:
      # Note: to avoid unintentional race conditions, no references to
      # modifiable objects should be returned unless they were created in this
      # function.
      mode = None
      owner_names = None

      if query.LQ_MODE in requested:
        if self.__deleted:
          mode = _DELETED_TEXT
          assert not (self.__exc or self.__shr)
        elif self.__exc:
          mode = _EXCLUSIVE_TEXT
        elif self.__shr:
          mode = _SHARED_TEXT

      # Current owner(s) are wanted
      if query.LQ_OWNER in requested:
        if self.__exc:
          owner = [self.__exc]
        else:
          owner = self.__shr

        if owner:
          assert not self.__deleted
          owner_names = [i.getName() for i in owner]

      # Pending acquires are wanted
      if query.LQ_PENDING in requested:
        pending = []

        # Sorting instead of copying and using heaq functions for simplicity
        for (_, prioqueue) in sorted(self.__pending):
          for cond in prioqueue:
            if cond.shared:
              pendmode = _SHARED_TEXT
            else:
              pendmode = _EXCLUSIVE_TEXT

            # List of names will be sorted in L{query._GetLockPending}
            pending.append((pendmode, [i.getName()
                                       for i in cond.get_waiting()]))
      else:
        pending = None

      return [(self.name, mode, owner_names, pending)]
    finally:
      self.__lock.release()

  def __check_deleted(self):
    """Raises an exception if the lock has been deleted.

    """
    if self.__deleted:
      raise errors.LockError("Deleted lock %s" % self.name)

  def __is_sharer(self):
    """Is the current thread sharing the lock at this time?

    """
    return threading.currentThread() in self.__shr

  def __is_exclusive(self):
    """Is the current thread holding the lock exclusively at this time?

    """
    return threading.currentThread() == self.__exc

  def __is_owned(self, shared=-1):
    """Is the current thread somehow owning the lock at this time?

    This is a private version of the function, which presumes you're holding
    the internal lock.

    """
    if shared < 0:
      return self.__is_sharer() or self.__is_exclusive()
    elif shared:
      return self.__is_sharer()
    else:
      return self.__is_exclusive()

  def is_owned(self, shared=-1):
    """Is the current thread somehow owning the lock at this time?

    @param shared:
        - < 0: check for any type of ownership (default)
        - 0: check for exclusive ownership
        - > 0: check for shared ownership

    """
    self.__lock.acquire()
    try:
      return self.__is_owned(shared=shared)
    finally:
      self.__lock.release()

  #: Necessary to remain compatible with threading.Condition, which tries to
  #: retrieve a locks' "_is_owned" attribute
  _is_owned = is_owned

  def _count_pending(self):
    """Returns the number of pending acquires.

    @rtype: int

    """
    self.__lock.acquire()
    try:
      return sum(len(prioqueue) for (_, prioqueue) in self.__pending)
    finally:
      self.__lock.release()

  def _check_empty(self):
    """Checks whether there are any pending acquires.

    @rtype: bool

    """
    self.__lock.acquire()
    try:
      # Order is important: __find_first_pending_queue modifies __pending
      (_, prioqueue) = self.__find_first_pending_queue()

      return not (prioqueue or
                  self.__pending or
                  self.__pending_by_prio or
                  self.__pending_shared)
    finally:
      self.__lock.release()

  def __do_acquire(self, shared):
    """Actually acquire the lock.

    """
    if shared:
      self.__shr.add(threading.currentThread())
    else:
      self.__exc = threading.currentThread()

  def __can_acquire(self, shared):
    """Determine whether lock can be acquired.

    """
    if shared:
      return self.__exc is None
    else:
      return len(self.__shr) == 0 and self.__exc is None

  def __find_first_pending_queue(self):
    """Tries to find the topmost queued entry with pending acquires.

    Removes empty entries while going through the list.

    """
    while self.__pending:
      (priority, prioqueue) = self.__pending[0]

      if prioqueue:
        return (priority, prioqueue)

      # Remove empty queue
      heapq.heappop(self.__pending)
      del self.__pending_by_prio[priority]
      assert priority not in self.__pending_shared

    return (None, None)

  def __is_on_top(self, cond):
    """Checks whether the passed condition is on top of the queue.

    The caller must make sure the queue isn't empty.

    """
    (_, prioqueue) = self.__find_first_pending_queue()

    return cond == prioqueue[0]

  def __acquire_unlocked(self, shared, timeout, priority):
    """Acquire a shared lock.

    @param shared: whether to acquire in shared mode; by default an
        exclusive lock will be acquired
    @param timeout: maximum waiting time before giving up
    @type priority: integer
    @param priority: Priority for acquiring lock

    """
    self.__check_deleted()

    # We cannot acquire the lock if we already have it
    assert not self.__is_owned(), ("double acquire() on a non-recursive lock"
                                   " %s" % self.name)

    # Remove empty entries from queue
    self.__find_first_pending_queue()

    # Check whether someone else holds the lock or there are pending acquires.
    if not self.__pending and self.__can_acquire(shared):
      # Apparently not, can acquire lock directly.
      self.__do_acquire(shared)
      return True

    # The lock couldn't be acquired right away, so if a timeout is given and is
    # considered too short, return right away as scheduling a pending
    # acquisition is quite expensive
    if timeout is not None and timeout < _LOCK_ACQUIRE_MIN_TIMEOUT:
      return False

    prioqueue = self.__pending_by_prio.get(priority, None)

    if shared:
      # Try to re-use condition for shared acquire
      wait_condition = self.__pending_shared.get(priority, None)
      assert (wait_condition is None or
              (wait_condition.shared and wait_condition in prioqueue))
    else:
      wait_condition = None

    if wait_condition is None:
      if prioqueue is None:
        assert priority not in self.__pending_by_prio

        prioqueue = []
        heapq.heappush(self.__pending, (priority, prioqueue))
        self.__pending_by_prio[priority] = prioqueue

      wait_condition = self.__condition_class(self.__lock, shared)
      prioqueue.append(wait_condition)

      if shared:
        # Keep reference for further shared acquires on same priority. This is
        # better than trying to find it in the list of pending acquires.
        assert priority not in self.__pending_shared
        self.__pending_shared[priority] = wait_condition

    wait_start = self.__time_fn()
    acquired = False

    try:
      # Wait until we become the topmost acquire in the queue or the timeout
      # expires.
      while True:
        if self.__is_on_top(wait_condition) and self.__can_acquire(shared):
          self.__do_acquire(shared)
          acquired = True
          break

        # A lot of code assumes blocking acquires always succeed, therefore we
        # can never return False for a blocking acquire
        if (timeout is not None and
            utils.TimeoutExpired(wait_start, timeout, _time_fn=self.__time_fn)):
          break

        # Wait for notification
        wait_condition.wait(timeout)
        self.__check_deleted()
    finally:
      # Remove condition from queue if there are no more waiters
      if not wait_condition.has_waiting():
        prioqueue.remove(wait_condition)
        if wait_condition.shared:
          # Remove from list of shared acquires if it wasn't while releasing
          # (e.g. on lock deletion)
          self.__pending_shared.pop(priority, None)

    return acquired

  def acquire(self, shared=0, timeout=None, priority=None,
              test_notify=None):
    """Acquire a shared lock.

    @type shared: integer (0/1) used as a boolean
    @param shared: whether to acquire in shared mode; by default an
        exclusive lock will be acquired
    @type timeout: float
    @param timeout: maximum waiting time before giving up
    @type priority: integer
    @param priority: Priority for acquiring lock
    @type test_notify: callable or None
    @param test_notify: Special callback function for unittesting

    """
    if priority is None:
      priority = _DEFAULT_PRIORITY

    self.__lock.acquire()
    try:
      # We already got the lock, notify now
      if __debug__ and callable(test_notify):
        test_notify()

      return self.__acquire_unlocked(shared, timeout, priority)
    finally:
      self.__lock.release()

  def downgrade(self):
    """Changes the lock mode from exclusive to shared.

    Pending acquires in shared mode on the same priority will go ahead.

    """
    self.__lock.acquire()
    try:
      assert self.__is_owned(), "Lock must be owned"

      if self.__is_exclusive():
        # Do nothing if the lock is already acquired in shared mode
        self.__exc = None
        self.__do_acquire(1)

        # Important: pending shared acquires should only jump ahead if there
        # was a transition from exclusive to shared, otherwise an owner of a
        # shared lock can keep calling this function to push incoming shared
        # acquires
        (priority, prioqueue) = self.__find_first_pending_queue()
        if prioqueue:
          # Is there a pending shared acquire on this priority?
          cond = self.__pending_shared.pop(priority, None)
          if cond:
            assert cond.shared
            assert cond in prioqueue

            # Ensure shared acquire is on top of queue
            if len(prioqueue) > 1:
              prioqueue.remove(cond)
              prioqueue.insert(0, cond)

            # Notify
            cond.notifyAll()

      assert not self.__is_exclusive()
      assert self.__is_sharer()

      return True
    finally:
      self.__lock.release()

  def release(self):
    """Release a Shared Lock.

    You must have acquired the lock, either in shared or in exclusive mode,
    before calling this function.

    """
    self.__lock.acquire()
    try:
      assert self.__is_exclusive() or self.__is_sharer(), \
        "Cannot release non-owned lock"

      # Autodetect release type
      if self.__is_exclusive():
        self.__exc = None
        notify = True
      else:
        self.__shr.remove(threading.currentThread())
        notify = not self.__shr

      # Notify topmost condition in queue if there are no owners left (for
      # shared locks)
      if notify:
        self.__notify_topmost()
    finally:
      self.__lock.release()

  def __notify_topmost(self):
    """Notifies topmost condition in queue of pending acquires.

    """
    (priority, prioqueue) = self.__find_first_pending_queue()
    if prioqueue:
      cond = prioqueue[0]
      cond.notifyAll()
      if cond.shared:
        # Prevent further shared acquires from sneaking in while waiters are
        # notified
        self.__pending_shared.pop(priority, None)

  def _notify_topmost(self):
    """Exported version of L{__notify_topmost}.

    """
    self.__lock.acquire()
    try:
      return self.__notify_topmost()
    finally:
      self.__lock.release()

  def delete(self, timeout=None, priority=None):
    """Delete a Shared Lock.

    This operation will declare the lock for removal. First the lock will be
    acquired in exclusive mode if you don't already own it, then the lock
    will be put in a state where any future and pending acquire() fail.

    @type timeout: float
    @param timeout: maximum waiting time before giving up
    @type priority: integer
    @param priority: Priority for acquiring lock

    """
    if priority is None:
      priority = _DEFAULT_PRIORITY

    self.__lock.acquire()
    try:
      assert not self.__is_sharer(), "Cannot delete() a lock while sharing it"

      self.__check_deleted()

      # The caller is allowed to hold the lock exclusively already.
      acquired = self.__is_exclusive()

      if not acquired:
        acquired = self.__acquire_unlocked(0, timeout, priority)

      if acquired:
        assert self.__is_exclusive() and not self.__is_sharer(), \
          "Lock wasn't acquired in exclusive mode"

        self.__deleted = True
        self.__exc = None

        assert not (self.__exc or self.__shr), "Found owner during deletion"

        # Notify all acquires. They'll throw an error.
        for (_, prioqueue) in self.__pending:
          for cond in prioqueue:
            cond.notifyAll()

        assert self.__deleted

      return acquired
    finally:
      self.__lock.release()

  def _release_save(self):
    shared = self.__is_sharer()
    self.release()
    return shared

  def _acquire_restore(self, shared):
    self.acquire(shared=shared)


# Whenever we want to acquire a full LockSet we pass None as the value
# to acquire.  Hide this behind this nicely named constant.
ALL_SET = None

LOCKSET_NAME = "[lockset]"


def _TimeoutZero():
  """Returns the number zero.

  """
  return 0


class _AcquireTimeout(Exception):
  """Internal exception to abort an acquire on a timeout.

  """


# Locking levels, must be acquired in increasing order. Current rules are:
# - At level LEVEL_CLUSTER resides the Big Ganeti Lock (BGL) which must be
#   acquired before performing any operation, either in shared or exclusive
#   mode. Acquiring the BGL in exclusive mode is discouraged and should be
#   avoided..
# - At levels LEVEL_NODE and LEVEL_INSTANCE reside node and instance locks. If
#   you need more than one node, or more than one instance, acquire them at the
#   same time.
# - LEVEL_NODE_RES is for node resources and should be used by operations with
#   possibly high impact on the node's disks.
(LEVEL_CLUSTER,
 LEVEL_INSTANCE,
 LEVEL_NODEGROUP,
 LEVEL_NODE,
 LEVEL_NODE_RES,
 LEVEL_NETWORK) = range(0, 6)

LEVELS = [
  LEVEL_CLUSTER,
  LEVEL_INSTANCE,
  LEVEL_NODEGROUP,
  LEVEL_NODE,
  LEVEL_NODE_RES,
  LEVEL_NETWORK,
  ]

# Lock levels which are modifiable
LEVELS_MOD = compat.UniqueFrozenset([
  LEVEL_NODE_RES,
  LEVEL_NODE,
  LEVEL_NODEGROUP,
  LEVEL_INSTANCE,
  LEVEL_NETWORK,
  ])

#: Lock level names (make sure to use singular form)
LEVEL_NAMES = {
  LEVEL_CLUSTER: "cluster",
  LEVEL_INSTANCE: "instance",
  LEVEL_NODEGROUP: "nodegroup",
  LEVEL_NODE: "node",
  LEVEL_NODE_RES: "node-res",
  LEVEL_NETWORK: "network",
  }

# Constant for the big ganeti lock
BGL = "BGL"
