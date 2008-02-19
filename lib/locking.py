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

