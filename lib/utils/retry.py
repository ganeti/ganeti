#
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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

"""Utility functions for retrying function calls with a timeout.

"""


import logging
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
      return fn(*args)
    except RetryAgain, err:
      retry_args = err.args
    except RetryTimeout:
      raise errors.ProgrammerError("Nested retry loop detected that didn't"
                                   " handle RetryTimeout")

    remaining_time = end_time - _time_fn()

    if remaining_time <= 0.0:
      raise RetryTimeout(*retry_args)

    assert remaining_time > 0.0

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


def CountRetry(expected, fn, count, args=None):
  """A wrapper over L{SimpleRetry} implementing a count down.

  Where L{Retry} fixes the time, after which the command is assumed to be
  failing, this function assumes the total number of tries.

  @see: L{Retry}
  """

  rdict = {"tries": 0}

  get_tries = lambda: rdict["tries"]

  def inc_tries(t):
    rdict["tries"] += t

  return SimpleRetry(expected, fn, 1, count, args=args,
                     wait_fn=inc_tries, _time_fn=get_tries)


def RetryByNumberOfTimes(max_retries, exception_class, fn, *args, **kwargs):
  """Retries calling a function up to the specified number of times.

  @type max_retries: integer
  @param max_retries: Maximum number of retries.
  @type exception_class: class
  @param exception_class: Exception class which is used for throwing the
                          final exception.
  @type fn: callable
  @param fn: Function to be called (up to the specified maximum number of
             retries.

  """
  last_exception = None
  for i in range(max_retries):
    try:
      fn(*args, **kwargs)
      break
    except errors.OpExecError as e:
      logging.error("Error after retry no. %s: %s.", i, e)
      last_exception = e
  else:
    if last_exception:
      raise exception_class("Error after %s retries. Last exception: %s."
                            % (max_retries, last_exception))
