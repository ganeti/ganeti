#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

"""Module implementing the Ganeti locking code."""

# pylint: disable=W0212

# W0212 since e.g. LockSet methods use (a lot) the internals of
# SharedLock

import os
import select
import threading
import errno
import weakref
import logging
import heapq
import itertools
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

# Internal lock acquisition modes for L{LockSet}
(_LS_ACQUIRE_EXACT,
 _LS_ACQUIRE_ALL) = range(1, 3)


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
    "_poller",
    ]

  def __init__(self, poller, fd):
    """Constructor for _SingleNotifyPipeConditionWaiter

    @type poller: select.poll
    @param poller: Poller object
    @type fd: int
    @param fd: File descriptor to wait for

    """
    object.__init__(self)
    self._poller = poller
    self._fd = fd

  def __call__(self, timeout):
    """Wait for something to happen on the pipe.

    @type timeout: float or None
    @param timeout: Timeout for waiting (can be None)

    """
    running_timeout = utils.RunningTimeout(timeout, True)

    while True:
      remaining_time = running_timeout.Remaining()

      if remaining_time is not None:
        if remaining_time < 0.0:
          break

        # Our calculation uses seconds, poll() wants milliseconds
        remaining_time *= 1000

      try:
        result = self._poller.poll(remaining_time)
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
    "_poller",
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
    self._poller = None

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
    self._poller = None

  def wait(self, timeout):
    """Wait for a notification.

    @type timeout: float or None
    @param timeout: Waiting timeout (can be None)

    """
    self._check_owned()
    self._check_unnotified()

    self._nwaiters += 1
    try:
      if self._poller is None:
        (self._read_fd, self._write_fd) = os.pipe()
        self._poller = select.poll()
        self._poller.register(self._read_fd, select.POLLHUP)

      wait_fn = self._waiter_class(self._poller, self._read_fd)
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
    @type monitor: L{LockMonitor}
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


class _AcquireTimeout(Exception):
  """Internal exception to abort an acquire on a timeout.

  """


class LockSet:
  """Implements a set of locks.

  This abstraction implements a set of shared locks for the same resource type,
  distinguished by name. The user can lock a subset of the resources and the
  LockSet will take care of acquiring the locks always in the same order, thus
  preventing deadlock.

  All the locks needed in the same set must be acquired together, though.

  @type name: string
  @ivar name: the name of the lockset

  """
  def __init__(self, members, name, monitor=None):
    """Constructs a new LockSet.

    @type members: list of strings
    @param members: initial members of the set
    @type monitor: L{LockMonitor}
    @param monitor: Lock monitor with which to register member locks

    """
    assert members is not None, "members parameter is not a list"
    self.name = name

    # Lock monitor
    self.__monitor = monitor

    # Used internally to guarantee coherency
    self.__lock = SharedLock(self._GetLockName("[lockset]"), monitor=monitor)

    # The lockdict indexes the relationship name -> lock
    # The order-of-locking is implied by the alphabetical order of names
    self.__lockdict = {}

    for mname in members:
      self.__lockdict[mname] = SharedLock(self._GetLockName(mname),
                                          monitor=monitor)

    # The owner dict contains the set of locks each thread owns. For
    # performance each thread can access its own key without a global lock on
    # this structure. It is paramount though that *no* other type of access is
    # done to this structure (eg. no looping over its keys). *_owner helper
    # function are defined to guarantee access is correct, but in general never
    # do anything different than __owners[threading.currentThread()], or there
    # will be trouble.
    self.__owners = {}

  def _GetLockName(self, mname):
    """Returns the name for a member lock.

    """
    return "%s/%s" % (self.name, mname)

  def _get_lock(self):
    """Returns the lockset-internal lock.

    """
    return self.__lock

  def _get_lockdict(self):
    """Returns the lockset-internal lock dictionary.

    Accessing this structure is only safe in single-thread usage or when the
    lockset-internal lock is held.

    """
    return self.__lockdict

  def is_owned(self):
    """Is the current thread a current level owner?

    @note: Use L{check_owned} to check if a specific lock is held

    """
    return threading.currentThread() in self.__owners

  def check_owned(self, names, shared=-1):
    """Check if locks are owned in a specific mode.

    @type names: sequence or string
    @param names: Lock names (or a single lock name)
    @param shared: See L{SharedLock.is_owned}
    @rtype: bool
    @note: Use L{is_owned} to check if the current thread holds I{any} lock and
      L{list_owned} to get the names of all owned locks

    """
    if isinstance(names, basestring):
      names = [names]

    # Avoid check if no locks are owned anyway
    if names and self.is_owned():
      candidates = []

      # Gather references to all locks (in case they're deleted in the meantime)
      for lname in names:
        try:
          lock = self.__lockdict[lname]
        except KeyError:
          raise errors.LockError("Non-existing lock '%s' in set '%s' (it may"
                                 " have been removed)" % (lname, self.name))
        else:
          candidates.append(lock)

      return compat.all(lock.is_owned(shared=shared) for lock in candidates)
    else:
      return False

  def owning_all(self):
    """Checks whether current thread owns internal lock.

    Holding the internal lock is equivalent with holding all locks in the set
    (the opposite does not necessarily hold as it can not be easily
    determined). L{add} and L{remove} require the internal lock.

    @rtype: boolean

    """
    return self.__lock.is_owned()

  def _add_owned(self, name=None):
    """Note the current thread owns the given lock"""
    if name is None:
      if not self.is_owned():
        self.__owners[threading.currentThread()] = set()
    else:
      if self.is_owned():
        self.__owners[threading.currentThread()].add(name)
      else:
        self.__owners[threading.currentThread()] = set([name])

  def _del_owned(self, name=None):
    """Note the current thread owns the given lock"""

    assert not (name is None and self.__lock.is_owned()), \
           "Cannot hold internal lock when deleting owner status"

    if name is not None:
      self.__owners[threading.currentThread()].remove(name)

    # Only remove the key if we don't hold the set-lock as well
    if not (self.__lock.is_owned() or
            self.__owners[threading.currentThread()]):
      del self.__owners[threading.currentThread()]

  def list_owned(self):
    """Get the set of resource names owned by the current thread"""
    if self.is_owned():
      return self.__owners[threading.currentThread()].copy()
    else:
      return set()

  def _release_and_delete_owned(self):
    """Release and delete all resources owned by the current thread"""
    for lname in self.list_owned():
      lock = self.__lockdict[lname]
      if lock.is_owned():
        lock.release()
      self._del_owned(name=lname)

  def __names(self):
    """Return the current set of names.

    Only call this function while holding __lock and don't iterate on the
    result after releasing the lock.

    """
    return self.__lockdict.keys()

  def _names(self):
    """Return a copy of the current set of elements.

    Used only for debugging purposes.

    """
    # If we don't already own the set-level lock acquired
    # we'll get it and note we need to release it later.
    release_lock = False
    if not self.__lock.is_owned():
      release_lock = True
      self.__lock.acquire(shared=1)
    try:
      result = self.__names()
    finally:
      if release_lock:
        self.__lock.release()
    return set(result)

  def acquire(self, names, timeout=None, shared=0, priority=None,
              test_notify=None):
    """Acquire a set of resource locks.

    @type names: list of strings (or string)
    @param names: the names of the locks which shall be acquired
        (special lock names, or instance/node names)
    @type shared: integer (0/1) used as a boolean
    @param shared: whether to acquire in shared mode; by default an
        exclusive lock will be acquired
    @type timeout: float or None
    @param timeout: Maximum time to acquire all locks
    @type priority: integer
    @param priority: Priority for acquiring locks
    @type test_notify: callable or None
    @param test_notify: Special callback function for unittesting

    @return: Set of all locks successfully acquired or None in case of timeout

    @raise errors.LockError: when any lock we try to acquire has
        been deleted before we succeed. In this case none of the
        locks requested will be acquired.

    """
    assert timeout is None or timeout >= 0.0

    # Check we don't already own locks at this level
    assert not self.is_owned(), ("Cannot acquire locks in the same set twice"
                                 " (lockset %s)" % self.name)

    if priority is None:
      priority = _DEFAULT_PRIORITY

    # We need to keep track of how long we spent waiting for a lock. The
    # timeout passed to this function is over all lock acquires.
    running_timeout = utils.RunningTimeout(timeout, False)

    try:
      if names is not None:
        # Support passing in a single resource to acquire rather than many
        if isinstance(names, basestring):
          names = [names]

        return self.__acquire_inner(names, _LS_ACQUIRE_EXACT, shared, priority,
                                    running_timeout.Remaining, test_notify)

      else:
        # If no names are given acquire the whole set by not letting new names
        # being added before we release, and getting the current list of names.
        # Some of them may then be deleted later, but we'll cope with this.
        #
        # We'd like to acquire this lock in a shared way, as it's nice if
        # everybody else can use the instances at the same time. If we are
        # acquiring them exclusively though they won't be able to do this
        # anyway, though, so we'll get the list lock exclusively as well in
        # order to be able to do add() on the set while owning it.
        if not self.__lock.acquire(shared=shared, priority=priority,
                                   timeout=running_timeout.Remaining()):
          raise _AcquireTimeout()
        try:
          # note we own the set-lock
          self._add_owned()

          return self.__acquire_inner(self.__names(), _LS_ACQUIRE_ALL, shared,
                                      priority, running_timeout.Remaining,
                                      test_notify)
        except:
          # We shouldn't have problems adding the lock to the owners list, but
          # if we did we'll try to release this lock and re-raise exception.
          # Of course something is going to be really wrong, after this.
          self.__lock.release()
          self._del_owned()
          raise

    except _AcquireTimeout:
      return None

  def __acquire_inner(self, names, mode, shared, priority,
                      timeout_fn, test_notify):
    """Inner logic for acquiring a number of locks.

    @param names: Names of the locks to be acquired
    @param mode: Lock acquisition mode
    @param shared: Whether to acquire in shared mode
    @param timeout_fn: Function returning remaining timeout
    @param priority: Priority for acquiring locks
    @param test_notify: Special callback function for unittesting

    """
    assert mode in (_LS_ACQUIRE_EXACT, _LS_ACQUIRE_ALL)

    acquire_list = []

    # First we look the locks up on __lockdict. We have no way of being sure
    # they will still be there after, but this makes it a lot faster should
    # just one of them be the already wrong. Using a sorted sequence to prevent
    # deadlocks.
    for lname in sorted(frozenset(names)):
      try:
        lock = self.__lockdict[lname] # raises KeyError if lock is not there
      except KeyError:
        # We are acquiring the whole set, it doesn't matter if this particular
        # element is not there anymore. If, however, only certain names should
        # be acquired, not finding a lock is an error.
        if mode == _LS_ACQUIRE_EXACT:
          raise errors.LockError("Lock '%s' not found in set '%s' (it may have"
                                 " been removed)" % (lname, self.name))
      else:
        acquire_list.append((lname, lock))

    # This will hold the locknames we effectively acquired.
    acquired = set()

    try:
      # Now acquire_list contains a sorted list of resources and locks we
      # want.  In order to get them we loop on this (private) list and
      # acquire() them.  We gave no real guarantee they will still exist till
      # this is done but .acquire() itself is safe and will alert us if the
      # lock gets deleted.
      for (lname, lock) in acquire_list:
        if __debug__ and callable(test_notify):
          test_notify_fn = lambda: test_notify(lname)
        else:
          test_notify_fn = None

        timeout = timeout_fn()

        try:
          # raises LockError if the lock was deleted
          acq_success = lock.acquire(shared=shared, timeout=timeout,
                                     priority=priority,
                                     test_notify=test_notify_fn)
        except errors.LockError:
          if mode == _LS_ACQUIRE_ALL:
            # We are acquiring the whole set, it doesn't matter if this
            # particular element is not there anymore.
            continue

          raise errors.LockError("Lock '%s' not found in set '%s' (it may have"
                                 " been removed)" % (lname, self.name))

        if not acq_success:
          # Couldn't get lock or timeout occurred
          if timeout is None:
            # This shouldn't happen as SharedLock.acquire(timeout=None) is
            # blocking.
            raise errors.LockError("Failed to get lock %s (set %s)" %
                                   (lname, self.name))

          raise _AcquireTimeout()

        try:
          # now the lock cannot be deleted, we have it!
          self._add_owned(name=lname)
          acquired.add(lname)

        except:
          # We shouldn't have problems adding the lock to the owners list, but
          # if we did we'll try to release this lock and re-raise exception.
          # Of course something is going to be really wrong after this.
          if lock.is_owned():
            lock.release()
          raise

    except:
      # Release all owned locks
      self._release_and_delete_owned()
      raise

    return acquired

  def downgrade(self, names=None):
    """Downgrade a set of resource locks from exclusive to shared mode.

    The locks must have been acquired in exclusive mode.

    """
    assert self.is_owned(), ("downgrade on lockset %s while not owning any"
                             " lock" % self.name)

    # Support passing in a single resource to downgrade rather than many
    if isinstance(names, basestring):
      names = [names]

    owned = self.list_owned()

    if names is None:
      names = owned
    else:
      names = set(names)
      assert owned.issuperset(names), \
        ("downgrade() on unheld resources %s (set %s)" %
         (names.difference(owned), self.name))

    for lockname in names:
      self.__lockdict[lockname].downgrade()

    # Do we own the lockset in exclusive mode?
    if self.__lock.is_owned(shared=0):
      # Have all locks been downgraded?
      if not compat.any(lock.is_owned(shared=0)
                        for lock in self.__lockdict.values()):
        self.__lock.downgrade()
        assert self.__lock.is_owned(shared=1)

    return True

  def release(self, names=None):
    """Release a set of resource locks, at the same level.

    You must have acquired the locks, either in shared or in exclusive mode,
    before releasing them.

    @type names: list of strings, or None
    @param names: the names of the locks which shall be released
        (defaults to all the locks acquired at that level).

    """
    assert self.is_owned(), ("release() on lock set %s while not owner" %
                             self.name)

    # Support passing in a single resource to release rather than many
    if isinstance(names, basestring):
      names = [names]

    if names is None:
      names = self.list_owned()
    else:
      names = set(names)
      assert self.list_owned().issuperset(names), (
               "release() on unheld resources %s (set %s)" %
               (names.difference(self.list_owned()), self.name))

    # First of all let's release the "all elements" lock, if set.
    # After this 'add' can work again
    if self.__lock.is_owned():
      self.__lock.release()
      self._del_owned()

    for lockname in names:
      # If we are sure the lock doesn't leave __lockdict without being
      # exclusively held we can do this...
      self.__lockdict[lockname].release()
      self._del_owned(name=lockname)

  def add(self, names, acquired=0, shared=0):
    """Add a new set of elements to the set

    @type names: list of strings
    @param names: names of the new elements to add
    @type acquired: integer (0/1) used as a boolean
    @param acquired: pre-acquire the new resource?
    @type shared: integer (0/1) used as a boolean
    @param shared: is the pre-acquisition shared?

    """
    # Check we don't already own locks at this level
    assert not self.is_owned() or self.__lock.is_owned(shared=0), \
      ("Cannot add locks if the set %s is only partially owned, or shared" %
       self.name)

    # Support passing in a single resource to add rather than many
    if isinstance(names, basestring):
      names = [names]

    # If we don't already own the set-level lock acquired in an exclusive way
    # we'll get it and note we need to release it later.
    release_lock = False
    if not self.__lock.is_owned():
      release_lock = True
      self.__lock.acquire()

    try:
      invalid_names = set(self.__names()).intersection(names)
      if invalid_names:
        # This must be an explicit raise, not an assert, because assert is
        # turned off when using optimization, and this can happen because of
        # concurrency even if the user doesn't want it.
        raise errors.LockError("duplicate add(%s) on lockset %s" %
                               (invalid_names, self.name))

      for lockname in names:
        lock = SharedLock(self._GetLockName(lockname), monitor=self.__monitor)

        if acquired:
          # No need for priority or timeout here as this lock has just been
          # created
          lock.acquire(shared=shared)
          # now the lock cannot be deleted, we have it!
          try:
            self._add_owned(name=lockname)
          except:
            # We shouldn't have problems adding the lock to the owners list,
            # but if we did we'll try to release this lock and re-raise
            # exception.  Of course something is going to be really wrong,
            # after this.  On the other hand the lock hasn't been added to the
            # __lockdict yet so no other threads should be pending on it. This
            # release is just a safety measure.
            lock.release()
            raise

        self.__lockdict[lockname] = lock

    finally:
      # Only release __lock if we were not holding it previously.
      if release_lock:
        self.__lock.release()

    return True

  def remove(self, names):
    """Remove elements from the lock set.

    You can either not hold anything in the lockset or already hold a superset
    of the elements you want to delete, exclusively.

    @type names: list of strings
    @param names: names of the resource to remove.

    @return: a list of locks which we removed; the list is always
        equal to the names list if we were holding all the locks
        exclusively

    """
    # Support passing in a single resource to remove rather than many
    if isinstance(names, basestring):
      names = [names]

    # If we own any subset of this lock it must be a superset of what we want
    # to delete. The ownership must also be exclusive, but that will be checked
    # by the lock itself.
    assert not self.is_owned() or self.list_owned().issuperset(names), (
      "remove() on acquired lockset %s while not owning all elements" %
      self.name)

    removed = []

    for lname in names:
      # Calling delete() acquires the lock exclusively if we don't already own
      # it, and causes all pending and subsequent lock acquires to fail. It's
      # fine to call it out of order because delete() also implies release(),
      # and the assertion above guarantees that if we either already hold
      # everything we want to delete, or we hold none.
      try:
        self.__lockdict[lname].delete()
        removed.append(lname)
      except (KeyError, errors.LockError):
        # This cannot happen if we were already holding it, verify:
        assert not self.is_owned(), ("remove failed while holding lockset %s" %
                                     self.name)
      else:
        # If no LockError was raised we are the ones who deleted the lock.
        # This means we can safely remove it from lockdict, as any further or
        # pending delete() or acquire() will fail (and nobody can have the lock
        # since before our call to delete()).
        #
        # This is done in an else clause because if the exception was thrown
        # it's the job of the one who actually deleted it.
        del self.__lockdict[lname]
        # And let's remove it from our private list if we owned it.
        if self.is_owned():
          self._del_owned(name=lname)

    return removed


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
# - LEVEL_NODE_ALLOC blocks instance allocations for the whole cluster
#   ("NAL" is the only lock at this level). It should be acquired in shared
#   mode when an opcode blocks all or a significant amount of a cluster's
#   locks. Opcodes doing instance allocations should acquire in exclusive mode.
#   Once the set of acquired locks for an opcode has been reduced to the working
#   set, the NAL should be released as well to allow allocations to proceed.
(LEVEL_CLUSTER,
 LEVEL_NODE_ALLOC,
 LEVEL_INSTANCE,
 LEVEL_NODEGROUP,
 LEVEL_NODE,
 LEVEL_NODE_RES,
 LEVEL_NETWORK) = range(0, 7)

LEVELS = [
  LEVEL_CLUSTER,
  LEVEL_NODE_ALLOC,
  LEVEL_INSTANCE,
  LEVEL_NODEGROUP,
  LEVEL_NODE,
  LEVEL_NODE_RES,
  LEVEL_NETWORK,
  ]

# Lock levels which are modifiable
LEVELS_MOD = frozenset([
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
  LEVEL_NODE_ALLOC: "node-alloc",
  }

# Constant for the big ganeti lock
BGL = "BGL"

#: Node allocation lock
NAL = "NAL"


class GanetiLockManager:
  """The Ganeti Locking Library

  The purpose of this small library is to manage locking for ganeti clusters
  in a central place, while at the same time doing dynamic checks against
  possible deadlocks. It will also make it easier to transition to a different
  lock type should we migrate away from python threads.

  """
  _instance = None

  def __init__(self, nodes, nodegroups, instances, networks):
    """Constructs a new GanetiLockManager object.

    There should be only a GanetiLockManager object at any time, so this
    function raises an error if this is not the case.

    @param nodes: list of node names
    @param nodegroups: list of nodegroup uuids
    @param instances: list of instance names

    """
    assert self.__class__._instance is None, \
           "double GanetiLockManager instance"

    self.__class__._instance = self

    self._monitor = LockMonitor()

    # The keyring contains all the locks, at their level and in the correct
    # locking order.
    self.__keyring = {
      LEVEL_CLUSTER: LockSet([BGL], "cluster", monitor=self._monitor),
      LEVEL_NODE: LockSet(nodes, "node", monitor=self._monitor),
      LEVEL_NODE_RES: LockSet(nodes, "node-res", monitor=self._monitor),
      LEVEL_NODEGROUP: LockSet(nodegroups, "nodegroup", monitor=self._monitor),
      LEVEL_INSTANCE: LockSet(instances, "instance", monitor=self._monitor),
      LEVEL_NETWORK: LockSet(networks, "network", monitor=self._monitor),
      LEVEL_NODE_ALLOC: LockSet([NAL], "node-alloc", monitor=self._monitor),
      }

    assert compat.all(ls.name == LEVEL_NAMES[level]
                      for (level, ls) in self.__keyring.items()), \
      "Keyring name mismatch"

  def AddToLockMonitor(self, provider):
    """Registers a new lock with the monitor.

    See L{LockMonitor.RegisterLock}.

    """
    return self._monitor.RegisterLock(provider)

  def QueryLocks(self, fields):
    """Queries information from all locks.

    See L{LockMonitor.QueryLocks}.

    """
    return self._monitor.QueryLocks(fields)

  def _names(self, level):
    """List the lock names at the given level.

    This can be used for debugging/testing purposes.

    @param level: the level whose list of locks to get

    """
    assert level in LEVELS, "Invalid locking level %s" % level
    return self.__keyring[level]._names()

  def is_owned(self, level):
    """Check whether we are owning locks at the given level

    """
    return self.__keyring[level].is_owned()

  def list_owned(self, level):
    """Get the set of owned locks at the given level

    """
    return self.__keyring[level].list_owned()

  def check_owned(self, level, names, shared=-1):
    """Check if locks at a certain level are owned in a specific mode.

    @see: L{LockSet.check_owned}

    """
    return self.__keyring[level].check_owned(names, shared=shared)

  def owning_all(self, level):
    """Checks whether current thread owns all locks at a certain level.

    @see: L{LockSet.owning_all}

    """
    return self.__keyring[level].owning_all()

  def _upper_owned(self, level):
    """Check that we don't own any lock at a level greater than the given one.

    """
    # This way of checking only works if LEVELS[i] = i, which we check for in
    # the test cases.
    return compat.any((self.is_owned(l) for l in LEVELS[level + 1:]))

  def _BGL_owned(self): # pylint: disable=C0103
    """Check if the current thread owns the BGL.

    Both an exclusive or a shared acquisition work.

    """
    return BGL in self.__keyring[LEVEL_CLUSTER].list_owned()

  @staticmethod
  def _contains_BGL(level, names): # pylint: disable=C0103
    """Check if the level contains the BGL.

    Check if acting on the given level and set of names will change
    the status of the Big Ganeti Lock.

    """
    return level == LEVEL_CLUSTER and (names is None or BGL in names)

  def acquire(self, level, names, timeout=None, shared=0, priority=None):
    """Acquire a set of resource locks, at the same level.

    @type level: member of locking.LEVELS
    @param level: the level at which the locks shall be acquired
    @type names: list of strings (or string)
    @param names: the names of the locks which shall be acquired
        (special lock names, or instance/node names)
    @type shared: integer (0/1) used as a boolean
    @param shared: whether to acquire in shared mode; by default
        an exclusive lock will be acquired
    @type timeout: float
    @param timeout: Maximum time to acquire all locks
    @type priority: integer
    @param priority: Priority for acquiring lock

    """
    assert level in LEVELS, "Invalid locking level %s" % level

    # Check that we are either acquiring the Big Ganeti Lock or we already own
    # it. Some "legacy" opcodes need to be sure they are run non-concurrently
    # so even if we've migrated we need to at least share the BGL to be
    # compatible with them. Of course if we own the BGL exclusively there's no
    # point in acquiring any other lock, unless perhaps we are half way through
    # the migration of the current opcode.
    assert (self._contains_BGL(level, names) or self._BGL_owned()), (
      "You must own the Big Ganeti Lock before acquiring any other")

    # Check we don't own locks at the same or upper levels.
    assert not self._upper_owned(level), ("Cannot acquire locks at a level"
                                          " while owning some at a greater one")

    # Acquire the locks in the set.
    return self.__keyring[level].acquire(names, shared=shared, timeout=timeout,
                                         priority=priority)

  def downgrade(self, level, names=None):
    """Downgrade a set of resource locks from exclusive to shared mode.

    You must have acquired the locks in exclusive mode.

    @type level: member of locking.LEVELS
    @param level: the level at which the locks shall be downgraded
    @type names: list of strings, or None
    @param names: the names of the locks which shall be downgraded
        (defaults to all the locks acquired at the level)

    """
    assert level in LEVELS, "Invalid locking level %s" % level

    return self.__keyring[level].downgrade(names=names)

  def release(self, level, names=None):
    """Release a set of resource locks, at the same level.

    You must have acquired the locks, either in shared or in exclusive
    mode, before releasing them.

    @type level: member of locking.LEVELS
    @param level: the level at which the locks shall be released
    @type names: list of strings, or None
    @param names: the names of the locks which shall be released
        (defaults to all the locks acquired at that level)

    """
    assert level in LEVELS, "Invalid locking level %s" % level
    assert (not self._contains_BGL(level, names) or
            not self._upper_owned(LEVEL_CLUSTER)), (
              "Cannot release the Big Ganeti Lock while holding something"
              " at upper levels (%r)" %
              (utils.CommaJoin(["%s=%r" % (LEVEL_NAMES[i], self.list_owned(i))
                                for i in self.__keyring.keys()]), ))

    # Release will complain if we don't own the locks already
    return self.__keyring[level].release(names)

  def add(self, level, names, acquired=0, shared=0):
    """Add locks at the specified level.

    @type level: member of locking.LEVELS_MOD
    @param level: the level at which the locks shall be added
    @type names: list of strings
    @param names: names of the locks to acquire
    @type acquired: integer (0/1) used as a boolean
    @param acquired: whether to acquire the newly added locks
    @type shared: integer (0/1) used as a boolean
    @param shared: whether the acquisition will be shared

    """
    assert level in LEVELS_MOD, "Invalid or immutable level %s" % level
    assert self._BGL_owned(), ("You must own the BGL before performing other"
                               " operations")
    assert not self._upper_owned(level), ("Cannot add locks at a level"
                                          " while owning some at a greater one")
    return self.__keyring[level].add(names, acquired=acquired, shared=shared)

  def remove(self, level, names):
    """Remove locks from the specified level.

    You must either already own the locks you are trying to remove
    exclusively or not own any lock at an upper level.

    @type level: member of locking.LEVELS_MOD
    @param level: the level at which the locks shall be removed
    @type names: list of strings
    @param names: the names of the locks which shall be removed
        (special lock names, or instance/node names)

    """
    assert level in LEVELS_MOD, "Invalid or immutable level %s" % level
    assert self._BGL_owned(), ("You must own the BGL before performing other"
                               " operations")
    # Check we either own the level or don't own anything from here
    # up. LockSet.remove() will check the case in which we don't own
    # all the needed resources, or we have a shared ownership.
    assert self.is_owned(level) or not self._upper_owned(level), (
           "Cannot remove locks at a level while not owning it or"
           " owning some at a greater one")
    return self.__keyring[level].remove(names)


def _MonitorSortKey((item, idx, num)):
  """Sorting key function.

  Sort by name, registration order and then order of information. This provides
  a stable sort order over different providers, even if they return the same
  name.

  """
  (name, _, _, _) = item

  return (utils.NiceSortKey(name), num, idx)


class LockMonitor(object):
  _LOCK_ATTR = "_lock"

  def __init__(self):
    """Initializes this class.

    """
    self._lock = SharedLock("LockMonitor")

    # Counter for stable sorting
    self._counter = itertools.count(0)

    # Tracked locks. Weak references are used to avoid issues with circular
    # references and deletion.
    self._locks = weakref.WeakKeyDictionary()

  @ssynchronized(_LOCK_ATTR)
  def RegisterLock(self, provider):
    """Registers a new lock.

    @param provider: Object with a callable method named C{GetLockInfo}, taking
      a single C{set} containing the requested information items
    @note: It would be nicer to only receive the function generating the
      requested information but, as it turns out, weak references to bound
      methods (e.g. C{self.GetLockInfo}) are tricky; there are several
      workarounds, but none of the ones I found works properly in combination
      with a standard C{WeakKeyDictionary}

    """
    assert provider not in self._locks, "Duplicate registration"

    # There used to be a check for duplicate names here. As it turned out, when
    # a lock is re-created with the same name in a very short timeframe, the
    # previous instance might not yet be removed from the weakref dictionary.
    # By keeping track of the order of incoming registrations, a stable sort
    # ordering can still be guaranteed.

    self._locks[provider] = self._counter.next()

  def _GetLockInfo(self, requested):
    """Get information from all locks.

    """
    # Must hold lock while getting consistent list of tracked items
    self._lock.acquire(shared=1)
    try:
      items = self._locks.items()
    finally:
      self._lock.release()

    return [(info, idx, num)
            for (provider, num) in items
            for (idx, info) in enumerate(provider.GetLockInfo(requested))]

  def _Query(self, fields):
    """Queries information from all locks.

    @type fields: list of strings
    @param fields: List of fields to return

    """
    qobj = query.Query(query.LOCK_FIELDS, fields)

    # Get all data with internal lock held and then sort by name and incoming
    # order
    lockinfo = sorted(self._GetLockInfo(qobj.RequestedData()),
                      key=_MonitorSortKey)

    # Extract lock information and build query data
    return (qobj, query.LockQueryData(map(compat.fst, lockinfo)))

  def QueryLocks(self, fields):
    """Queries information from all locks.

    @type fields: list of strings
    @param fields: List of fields to return

    """
    (qobj, ctx) = self._Query(fields)

    # Prepare query response
    return query.GetQueryResponse(qobj, ctx)
