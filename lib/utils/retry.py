#
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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

"""Utility functions for retrying function calls with a timeout.

"""


import time

from ganeti import errors


#: Special delay to specify whole remaining timeout
RETRY_REMAINING_TIME = object()


class RetryTimeout(Exception):
  """Retry loop timed out.

  Any arguments which was passed by the retried function to RetryAgain will be
  preserved in RetryTimeout, if it is raised. If such argument was an exception
  the RaiseInner helper method will reraise it.

  """
  def RaiseInner(self):
    if self.args and isinstance(self.args[0], Exception):
      raise self.args[0]
    else:
      raise RetryTimeout(*self.args)


class RetryAgain(Exception):
  """Retry again.

  Any arguments passed to RetryAgain will be preserved, if a timeout occurs, as
  arguments to RetryTimeout. If an exception is passed, the RaiseInner() method
  of the RetryTimeout() method can be used to reraise it.

  """


class _RetryDelayCalculator(object):
  """Calculator for increasing delays.

  """
  __slots__ = [
    "_factor",
    "_limit",
    "_next",
    "_start",
    ]

  def __init__(self, start, factor, limit):
    """Initializes this class.

    @type start: float
    @param start: Initial delay
    @type factor: float
    @param factor: Factor for delay increase
    @type limit: float or None
    @param limit: Upper limit for delay or None for no limit

    """
    assert start > 0.0
    assert factor >= 1.0
    assert limit is None or limit >= 0.0

    self._start = start
    self._factor = factor
    self._limit = limit

    self._next = start

  def __call__(self):
    """Returns current delay and calculates the next one.

    """
    current = self._next

    # Update for next run
    if self._limit is None or self._next < self._limit:
      self._next = min(self._limit, self._next * self._factor)

    return current


def Retry(fn, delay, timeout, args=None, wait_fn=time.sleep,
          _time_fn=time.time):
  """Call a function repeatedly until it succeeds.

  The function C{fn} is called repeatedly until it doesn't throw L{RetryAgain}
  anymore. Between calls a delay, specified by C{delay}, is inserted. After a
  total of C{timeout} seconds, this function throws L{RetryTimeout}.

  C{delay} can be one of the following:
    - callable returning the delay length as a float
    - Tuple of (start, factor, limit)
    - L{RETRY_REMAINING_TIME} to sleep until the timeout expires (this is
      useful when overriding L{wait_fn} to wait for an external event)
    - A static delay as a number (int or float)

  @type fn: callable
  @param fn: Function to be called
  @param delay: Either a callable (returning the delay), a tuple of (start,
                factor, limit) (see L{_RetryDelayCalculator}),
                L{RETRY_REMAINING_TIME} or a number (int or float)
  @type timeout: float
  @param timeout: Total timeout
  @type wait_fn: callable
  @param wait_fn: Waiting function
  @return: Return value of function

  """
  assert callable(fn)
  assert callable(wait_fn)
  assert callable(_time_fn)

  if args is None:
    args = []

  end_time = _time_fn() + timeout

  if callable(delay):
    # External function to calculate delay
    calc_delay = delay

  elif isinstance(delay, (tuple, list)):
    # Increasing delay with optional upper boundary
    (start, factor, limit) = delay
    calc_delay = _RetryDelayCalculator(start, factor, limit)

  elif delay is RETRY_REMAINING_TIME:
    # Always use the remaining time
    calc_delay = None

  else:
    # Static delay
    calc_delay = lambda: delay

  assert calc_delay is None or callable(calc_delay)

  while True:
    retry_args = []
    try:
      # pylint: disable-msg=W0142
      return fn(*args)
    except RetryAgain, err:
      retry_args = err.args
    except RetryTimeout:
      raise errors.ProgrammerError("Nested retry loop detected that didn't"
                                   " handle RetryTimeout")

    remaining_time = end_time - _time_fn()

    if remaining_time < 0.0:
      # pylint: disable-msg=W0142
      raise RetryTimeout(*retry_args)

    assert remaining_time >= 0.0

    if calc_delay is None:
      wait_fn(remaining_time)
    else:
      current_delay = calc_delay()
      if current_delay > 0.0:
        wait_fn(current_delay)


def SimpleRetry(expected, fn, delay, timeout, args=None, wait_fn=time.sleep,
                _time_fn=time.time):
  """A wrapper over L{Retry} implementing a simpler interface.

  All the parameters are the same as for L{Retry}, except it has one
  extra argument: expected, which can be either a value (will be
  compared with the result of the function, or a callable (which will
  get the result passed and has to return a boolean). If the test is
  false, we will retry until either the timeout has passed or the
  tests succeeds. In both cases, the last result from calling the
  function will be returned.

  Note that this function is not expected to raise any retry-related
  exceptions, always simply returning values. As such, the function is
  designed to allow easy wrapping of code that doesn't use retry at
  all (e.g. "if fn(args)" replaced with "if SimpleRetry(True, fn,
  ...)".

  @see: L{Retry}

  """
  rdict = {}
  def helper(*innerargs):
    # pylint: disable-msg=W0142
    result = rdict["result"] = fn(*innerargs)
    if not ((callable(expected) and expected(result)) or result == expected):
      raise RetryAgain()
    return result

  try:
    result = Retry(helper, delay, timeout, args=args,
                   wait_fn=wait_fn, _time_fn=_time_fn)
  except RetryTimeout:
    assert "result" in rdict
    result = rdict["result"]
  return result
