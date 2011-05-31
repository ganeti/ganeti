#
#

# Copyright (C) 2011 Google Inc.
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


"""This module implements caching."""


import time

from ganeti import locking
from ganeti import serializer


TIMESTAMP = "timestamp"
TTL = "ttl"
VALUE = "value"


class CacheBase:
  """This is the base class for all caches.

  """
  def __init__(self):
    """Base init method.

    """

  def Store(self, key, value, ttl=0):
    """Stores key with value in the cache.

    @param key: The key to associate this cached value
    @param value: The value to cache
    @param ttl: TTL in seconds after when this entry is considered outdated
    @returns: L{True} on success, L{False} on failure

    """
    raise NotImplementedError

  def GetMulti(self, keys):
    """Retrieve multiple values from the cache.

    @param keys: The keys to retrieve
    @returns: The list of values

    """
    raise NotImplementedError

  def Get(self, key):
    """Retrieve the value from the cache.

    @param key: The key to retrieve
    @returns: The value or L{None} if not found

    """
    raise NotImplementedError

  def Invalidate(self, keys):
    """Invalidate given keys.

    @param keys: The list of keys to invalidate
    @returns: L{True} on success, L{False} otherwise

    """
    raise NotImplementedError

  def Flush(self):
    """Invalidates all of the keys and flushes the cache.

    """
    raise NotImplementedError

  def ResetState(self):
    """Used to reset the state of the cache.

    This can be used to reinstantiate connection or any other state refresh

    """

  def Cleanup(self):
    """Cleanup the cache from expired entries.

    """


class SimpleCache(CacheBase):
  """Implements a very simple, dict base cache.

  """
  CLEANUP_ROUND = 1800
  _LOCK = "lock"

  def __init__(self, _time_fn=time.time):
    """Initialize this class.

    @param _time_fn: Function used to return time (unittest only)

    """
    CacheBase.__init__(self)

    self._time_fn = _time_fn

    self.cache = {}
    self.lock = locking.SharedLock("SimpleCache")
    self.last_cleanup = self._time_fn()

  def _UnlockedCleanup(self):
    """Does cleanup of the cache.

    """
    check_time = self._time_fn()
    if (self.last_cleanup + self.CLEANUP_ROUND) <= check_time:
      keys = []
      for key, value in self.cache.items():
        if not value[TTL]:
          continue

        expired = value[TIMESTAMP] + value[TTL]
        if expired < check_time:
          keys.append(key)
      self._UnlockedInvalidate(keys)
      self.last_cleanup = check_time

  @locking.ssynchronized(_LOCK)
  def Cleanup(self):
    """Cleanup our cache.

    """
    self._UnlockedCleanup()

  @locking.ssynchronized(_LOCK)
  def Store(self, key, value, ttl=0):
    """Stores a value at key in the cache.

    See L{CacheBase.Store} for parameter description

    """
    assert ttl >= 0
    self._UnlockedCleanup()
    val = serializer.Dump(value)
    cache_val = {
      TIMESTAMP: self._time_fn(),
      TTL: ttl,
      VALUE: val
      }
    self.cache[key] = cache_val
    return True

  @locking.ssynchronized(_LOCK, shared=1)
  def GetMulti(self, keys):
    """Retrieve the values of keys from cache.

    See L{CacheBase.GetMulti} for parameter description

    """
    return [self._ExtractValue(key) for key in keys]

  @locking.ssynchronized(_LOCK, shared=1)
  def Get(self, key):
    """Retrieve the value of key from cache.

    See L{CacheBase.Get} for parameter description

    """
    return self._ExtractValue(key)

  @locking.ssynchronized(_LOCK)
  def Invalidate(self, keys):
    """Invalidates value for keys in cache.

    See L{CacheBase.Invalidate} for parameter description

    """
    return self._UnlockedInvalidate(keys)

  @locking.ssynchronized(_LOCK)
  def Flush(self):
    """Invalidates all keys and values in cache.

    See L{CacheBase.Flush} for parameter description

    """
    self.cache.clear()
    self.last_cleanup = self._time_fn()

  def _UnlockedInvalidate(self, keys):
    """Invalidate keys in cache.

    This is the unlocked version, see L{Invalidate} for parameter description

    """
    for key in keys:
      self.cache.pop(key, None)

    return True

  def _ExtractValue(self, key):
    """Extracts just the value for a key.

    This method is taking care if the value did not expire ans returns it

    @param key: The key to look for
    @returns: The value if key is not expired, L{None} otherwise

    """
    try:
      cache_val = self.cache[key]
    except KeyError:
      return None
    else:
      if cache_val[TTL] == 0:
        return serializer.Load(cache_val[VALUE])
      else:
        expired = cache_val[TIMESTAMP] + cache_val[TTL]

        if self._time_fn() <= expired:
          return serializer.Load(cache_val[VALUE])
        else:
          return None
