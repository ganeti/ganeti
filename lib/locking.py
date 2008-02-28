#
#

# Copyright (C) 2006, 2007 Google Inc.
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

# pylint: disable-msg=W0613,W0201

import threading
# Wouldn't it be better to define LockingError in the locking module?
# Well, for now that's how the rest of the code does it...
from ganeti import errors


class SharedLock:
  """Implements a shared lock.

  Multiple threads can acquire the lock in a shared way, calling
  acquire_shared().  In order to acquire the lock in an exclusive way threads
  can call acquire_exclusive().

  The lock prevents starvation but does not guarantee that threads will acquire
  the shared lock in the order they queued for it, just that they will
  eventually do so.

  """
  def __init__(self):
    """Construct a new SharedLock"""
    # we have two conditions, c_shr and c_exc, sharing the same lock.
    self.__lock = threading.Lock()
    self.__turn_shr = threading.Condition(self.__lock)
    self.__turn_exc = threading.Condition(self.__lock)

    # current lock holders
    self.__shr = set()
    self.__exc = None

    # lock waiters
    self.__nwait_exc = 0
    self.__nwait_shr = 0

    # is this lock in the deleted state?
    self.__deleted = False

  def __is_sharer(self):
    """Is the current thread sharing the lock at this time?"""
    return threading.currentThread() in self.__shr

  def __is_exclusive(self):
    """Is the current thread holding the lock exclusively at this time?"""
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

  def _is_owned(self, shared=-1):
    """Is the current thread somehow owning the lock at this time?

    Args:
      shared:
        < 0: check for any type of ownership (default)
        0: check for exclusive ownership
        > 0: check for shared ownership

    """
    self.__lock.acquire()
    try:
      result = self.__is_owned(shared)
    finally:
      self.__lock.release()

    return result

  def __wait(self,c):
    """Wait on the given condition, and raise an exception if the current lock
    is declared deleted in the meantime.

    Args:
      c: condition to wait on

    """
    c.wait()
    if self.__deleted:
      raise errors.LockError('deleted lock')

  def __exclusive_acquire(self):
    """Acquire the lock exclusively.

    This is a private function that presumes you are already holding the
    internal lock. It's defined separately to avoid code duplication between
    acquire() and delete()

    """
    self.__nwait_exc += 1
    try:
      # This is to save ourselves from a nasty race condition that could
      # theoretically make the sharers starve.
      if self.__nwait_shr > 0 or self.__nwait_exc > 1:
        self.__wait(self.__turn_exc)

      while len(self.__shr) > 0 or self.__exc is not None:
        self.__wait(self.__turn_exc)

      self.__exc = threading.currentThread()
    finally:
      self.__nwait_exc -= 1


  def acquire(self, blocking=1, shared=0):
    """Acquire a shared lock.

    Args:
      shared: whether to acquire in shared mode. By default an exclusive lock
              will be acquired.
      blocking: whether to block while trying to acquire or to operate in try-lock mode.
                this locking mode is not supported yet.

    """
    if not blocking:
      # We don't have non-blocking mode for now
      raise NotImplementedError

    self.__lock.acquire()
    try:
      if self.__deleted:
        raise errors.LockError('deleted lock')

      # We cannot acquire the lock if we already have it
      assert not self.__is_owned(), "double acquire() on a non-recursive lock"

      if shared:
        self.__nwait_shr += 1
        try:
          # If there is an exclusive holder waiting we have to wait.  We'll
          # only do this once, though, when we start waiting for the lock. Then
          # we'll just wait while there are no exclusive holders.
          if self.__nwait_exc > 0:
            # TODO: if !blocking...
            self.__wait(self.__turn_shr)

          while self.__exc is not None:
            # TODO: if !blocking...
            self.__wait(self.__turn_shr)

          self.__shr.add(threading.currentThread())
        finally:
          self.__nwait_shr -= 1

      else:
        # TODO: if !blocking...
        # (or modify __exclusive_acquire for non-blocking mode)
        self.__exclusive_acquire()

    finally:
      self.__lock.release()

    return True

  def release(self):
    """Release a Shared Lock.

    You must have acquired the lock, either in shared or in exclusive mode,
    before calling this function.

    """
    self.__lock.acquire()
    try:
      # Autodetect release type
      if self.__is_exclusive():
        self.__exc = None

        # An exclusive holder has just had the lock, time to put it in shared
        # mode if there are shared holders waiting. Otherwise wake up the next
        # exclusive holder.
        if self.__nwait_shr > 0:
          self.__turn_shr.notifyAll()
        elif self.__nwait_exc > 0:
         self.__turn_exc.notify()

      elif self.__is_sharer():
        self.__shr.remove(threading.currentThread())

        # If there are shared holders waiting there *must* be an exclusive holder
        # waiting as well; otherwise what were they waiting for?
        assert (self.__nwait_shr == 0 or self.__nwait_exc > 0,
                "Lock sharers waiting while no exclusive is queueing")

        # If there are no more shared holders and some exclusive holders are
        # waiting let's wake one up.
        if len(self.__shr) == 0 and self.__nwait_exc > 0:
          self.__turn_exc.notify()

      else:
        assert False, "Cannot release non-owned lock"

    finally:
      self.__lock.release()

  def delete(self, blocking=1):
    """Delete a Shared Lock.

    This operation will declare the lock for removal. First the lock will be
    acquired in exclusive mode if you don't already own it, then the lock
    will be put in a state where any future and pending acquire() fail.

    Args:
      blocking: whether to block while trying to acquire or to operate in
                try-lock mode.  this locking mode is not supported yet unless
                you are already holding exclusively the lock.

    """
    self.__lock.acquire()
    try:
      assert not self.__is_sharer(), "cannot delete() a lock while sharing it"

      if self.__deleted:
        raise errors.LockError('deleted lock')

      if not self.__is_exclusive():
        if not blocking:
          # We don't have non-blocking mode for now
          raise NotImplementedError
        self.__exclusive_acquire()

      self.__deleted = True
      self.__exc = None
      # Wake up everybody, they will fail acquiring the lock and
      # raise an exception instead.
      self.__turn_exc.notifyAll()
      self.__turn_shr.notifyAll()

    finally:
      self.__lock.release()


class LockSet:
  """Implements a set of locks.

  This abstraction implements a set of shared locks for the same resource type,
  distinguished by name. The user can lock a subset of the resources and the
  LockSet will take care of acquiring the locks always in the same order, thus
  preventing deadlock.

  All the locks needed in the same set must be acquired together, though.

  """
  def __init__(self, members=None):
    """Constructs a new LockSet.

    Args:
      members: initial members of the set

    """
    # Used internally to guarantee coherency.
    self.__lock = SharedLock()

    # The lockdict indexes the relationship name -> lock
    # The order-of-locking is implied by the alphabetical order of names
    self.__lockdict = {}

    if members is not None:
      for name in members:
        self.__lockdict[name] = SharedLock()

    # The owner dict contains the set of locks each thread owns. For
    # performance each thread can access its own key without a global lock on
    # this structure. It is paramount though that *no* other type of access is
    # done to this structure (eg. no looping over its keys). *_owner helper
    # function are defined to guarantee access is correct, but in general never
    # do anything different than __owners[threading.currentThread()], or there
    # will be trouble.
    self.__owners = {}

  def _is_owned(self):
    """Is the current thread a current level owner?"""
    return threading.currentThread() in self.__owners

  def _add_owned(self, name):
    """Note the current thread owns the given lock"""
    if self._is_owned():
      self.__owners[threading.currentThread()].add(name)
    else:
       self.__owners[threading.currentThread()] = set([name])

  def _del_owned(self, name):
    """Note the current thread owns the given lock"""
    self.__owners[threading.currentThread()].remove(name)

    if not self.__owners[threading.currentThread()]:
      del self.__owners[threading.currentThread()]

  def _list_owned(self):
    """Get the set of resource names owned by the current thread"""
    if self._is_owned():
      return self.__owners[threading.currentThread()].copy()
    else:
      return set()

  def __names(self):
    """Return the current set of names.

    Only call this function while holding __lock and don't iterate on the
    result after releasing the lock.

    """
    return set(self.__lockdict.keys())

  def _names(self):
    """Return a copy of the current set of elements.

    Used only for debugging purposes.
    """
    self.__lock.acquire(shared=1)
    try:
      result = self.__names()
    finally:
      self.__lock.release()
    return result

  def acquire(self, names, blocking=1, shared=0):
    """Acquire a set of resource locks.

    Args:
      names: the names of the locks which shall be acquired.
             (special lock names, or instance/node names)
      shared: whether to acquire in shared mode. By default an exclusive lock
              will be acquired.
      blocking: whether to block while trying to acquire or to operate in try-lock mode.
                this locking mode is not supported yet.

    Returns:
      True: when all the locks are successfully acquired

    Raises:
      errors.LockError: when any lock we try to acquire has been deleted
      before we succeed. In this case none of the locks requested will be
      acquired.

    """
    if not blocking:
      # We don't have non-blocking mode for now
      raise NotImplementedError

    # Check we don't already own locks at this level
    assert not self._is_owned(), "Cannot acquire locks in the same set twice"

    # Support passing in a single resource to acquire rather than many
    if isinstance(names, basestring):
      names = [names]
    else:
      names.sort()

    acquire_list = []
    # First we look the locks up on __lockdict. We have no way of being sure
    # they will still be there after, but this makes it a lot faster should
    # just one of them be the already wrong
    try:
      for lname in names:
        lock = self.__lockdict[lname] # raises KeyError if the lock is not there
        acquire_list.append((lname, lock))
    except (KeyError):
      raise errors.LockError('non-existing lock in set (%s)' % lname)

    # Now acquire_list contains a sorted list of resources and locks we want.
    # In order to get them we loop on this (private) list and acquire() them.
    # We gave no real guarantee they will still exist till this is done but
    # .acquire() itself is safe and will alert us if the lock gets deleted.
    try:
      for (lname, lock) in acquire_list:
        lock.acquire(shared=shared) # raises LockError if the lock is deleted
        try:
          # now the lock cannot be deleted, we have it!
          self._add_owned(lname)
        except:
          # We shouldn't have problems adding the lock to the owners list, but
          # if we did we'll try to release this lock and re-raise exception.
          # Of course something is going to be really wrong, after this.
          lock.release()
          raise

    except (errors.LockError):
      name_fail = lname
      for lname in self._list_owned():
        self.__lockdict[lname].release()
        self._del_owned(lname)
      raise errors.LockError('non-existing lock in set (%s)' % name_fail)

    return True

  def release(self, names=None):
    """Release a set of resource locks, at the same level.

    You must have acquired the locks, either in shared or in exclusive mode,
    before releasing them.

    Args:
      names: the names of the locks which shall be released.
             (defaults to all the locks acquired at that level).

    """

    assert self._is_owned(), "release() on lock set while not owner"

    # Support passing in a single resource to release rather than many
    if isinstance(names, basestring):
      names = [names]

    if names is None:
      names = self._list_owned()
    else:
      names = set(names)
      assert self._list_owned().issuperset(names), (
               "release() on unheld resources %s" %
               names.difference(self._list_owned()))

    for lockname in names:
      # If we are sure the lock doesn't leave __lockdict without being
      # exclusively held we can do this...
      self.__lockdict[lockname].release()
      self._del_owned(lockname)

  def add(self, names, acquired=0, shared=0):
    """Add a new set of elements to the set

    Args:
      names: names of the new elements to add
      acquired: pre-acquire the new resource?
      shared: is the pre-acquisition shared?

    """
    # Support passing in a single resource to add rather than many
    if isinstance(names, basestring):
      names = [names]

    # Acquire the internal lock in an exclusive way, so there cannot be a
    # conflicting add()
    self.__lock.acquire()
    try:
      invalid_names = self.__names().intersection(names)
      if invalid_names:
        # This must be an explicit raise, not an assert, because assert is
        # turned off when using optimization, and this can happen because of
        # concurrency even if the user doesn't want it.
        raise errors.LockError("duplicate add() (%s)" % invalid_names)

      for lockname in names:
        lock = SharedLock()

        if acquired:
          lock.acquire(shared=shared)
          # now the lock cannot be deleted, we have it!
          try:
            self._add_owned(lockname)
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
      self.__lock.release()

    return True

  def remove(self, names, blocking=1):
    """Remove elements from the lock set.

    You can either not hold anything in the lockset or already hold a superset
    of the elements you want to delete, exclusively.

    Args:
      names: names of the resource to remove.
      blocking: whether to block while trying to acquire or to operate in
                try-lock mode.  this locking mode is not supported yet unless
                you are already holding exclusively the locks.

    Returns:
      A list of lock which we failed to delete. The list is always empty if we
      were holding all the locks exclusively.

    """
    if not blocking and not self._is_owned():
      # We don't have non-blocking mode for now
      raise NotImplementedError

    # Support passing in a single resource to remove rather than many
    if isinstance(names, basestring):
      names = [names]

    # If we own any subset of this lock it must be a superset of what we want
    # to delete. The ownership must also be exclusive, but that will be checked
    # by the lock itself.
    assert not self._is_owned() or self._list_owned().issuperset(names), (
      "remove() on acquired lockset while not owning all elements")

    delete_failed=[]

    for lname in names:
      # Calling delete() acquires the lock exclusively if we don't already own
      # it, and causes all pending and subsequent lock acquires to fail. It's
      # fine to call it out of order because delete() also implies release(),
      # and the assertion above guarantees that if we either already hold
      # everything we want to delete, or we hold none.
      try:
        self.__lockdict[lname].delete()
      except (KeyError, errors.LockError):
        delete_failed.append(lname)
        # This cannot happen if we were already holding it, verify:
        assert not self._is_owned(), "remove failed while holding lockset"
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
        if self._is_owned():
          self._del_owned(lname)

    return delete_failed

