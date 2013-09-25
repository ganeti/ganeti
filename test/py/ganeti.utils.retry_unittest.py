#!/usr/bin/python
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


"""Script for testing ganeti.utils.retry"""

import unittest

from ganeti import constants
from ganeti import errors
from ganeti import utils

import testutils


class TestRetry(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.retries = 0
    self.called = 0
    self.time = 1379601882.0
    self.time_for_time_fn = 0
    self.time_for_retry_and_succeed = 0

  def _time_fn(self):
    self.time += self.time_for_time_fn
    return self.time

  def _wait_fn(self, delay):
    self.time += delay

  @staticmethod
  def _RaiseRetryAgain():
    raise utils.RetryAgain()

  @staticmethod
  def _RaiseRetryAgainWithArg(args):
    raise utils.RetryAgain(*args)

  def _WrongNestedLoop(self):
    return utils.Retry(self._RaiseRetryAgain, 0.01, 0.02)

  def _RetryAndSucceed(self, retries):
    self.time += self.time_for_retry_and_succeed
    if self.retries < retries:
      self.retries += 1
      raise utils.RetryAgain()
    else:
      return True

  def _SimpleRetryAndSucceed(self, retries):
    self.called += 1
    if self.retries < retries:
      self.retries += 1
      return False
    else:
      return True

  def testRaiseTimeout(self):
    self.failUnlessRaises(utils.RetryTimeout, utils.Retry,
                          self._RaiseRetryAgain, 0.01, 0.02,
                          wait_fn = self._wait_fn, _time_fn = self._time_fn)
    self.failUnlessRaises(utils.RetryTimeout, utils.Retry,
                          self._RetryAndSucceed, 0.01, 0, args=[1],
                          wait_fn = self._wait_fn, _time_fn = self._time_fn)
    self.failUnlessEqual(self.retries, 1)

  def testComplete(self):
    self.failUnlessEqual(utils.Retry(lambda: True, 0, 1,
                                     wait_fn = self._wait_fn,
                                     _time_fn = self._time_fn),
                         True)
    self.failUnlessEqual(utils.Retry(self._RetryAndSucceed, 0, 1, args=[2],
                                     wait_fn = self._wait_fn,
                                     _time_fn = self._time_fn),
                         True)
    self.failUnlessEqual(self.retries, 2)

  def testCompleteNontrivialTimes(self):
    self.time_for_time_fn = 0.01
    self.time_for_retry_and_succeed = 0.1
    self.failUnlessEqual(utils.Retry(self._RetryAndSucceed, 0, 1, args=[2],
                                     wait_fn = self._wait_fn,
                                     _time_fn = self._time_fn),
                         True)
    self.failUnlessEqual(self.retries, 2)

  def testNestedLoop(self):
    try:
      self.failUnlessRaises(errors.ProgrammerError, utils.Retry,
                            self._WrongNestedLoop, 0, 1,
                            wait_fn = self._wait_fn, _time_fn = self._time_fn)
    except utils.RetryTimeout:
      self.fail("Didn't detect inner loop's exception")

  def testTimeoutArgument(self):
    retry_arg="my_important_debugging_message"
    try:
      utils.Retry(self._RaiseRetryAgainWithArg, 0.01, 0.02, args=[[retry_arg]],
                  wait_fn = self._wait_fn, _time_fn = self._time_fn)
    except utils.RetryTimeout, err:
      self.failUnlessEqual(err.args, (retry_arg, ))
    else:
      self.fail("Expected timeout didn't happen")

  def testTimeout(self):
    self.time_for_time_fn = 0.01
    self.time_for_retry_and_succeed = 10
    try:
      utils.Retry(self._RetryAndSucceed, 1, 18, args=[2],
                  wait_fn = self._wait_fn, _time_fn = self._time_fn)
    except utils.RetryTimeout, err:
      self.failUnlessEqual(err.args, ())
    else:
      self.fail("Expected timeout didn't happen")

  def testNoTimeout(self):
    self.time_for_time_fn = 0.01
    self.time_for_retry_and_succeed = 8
    self.failUnlessEqual(
      utils.Retry(self._RetryAndSucceed, 1, 18, args=[2],
                  wait_fn = self._wait_fn, _time_fn = self._time_fn),
      True)

  def testRaiseInnerWithExc(self):
    retry_arg="my_important_debugging_message"
    try:
      try:
        utils.Retry(self._RaiseRetryAgainWithArg, 0.01, 0.02,
                    args=[[errors.GenericError(retry_arg, retry_arg)]],
                    wait_fn = self._wait_fn, _time_fn = self._time_fn)
      except utils.RetryTimeout, err:
        err.RaiseInner()
      else:
        self.fail("Expected timeout didn't happen")
    except errors.GenericError, err:
      self.failUnlessEqual(err.args, (retry_arg, retry_arg))
    else:
      self.fail("Expected GenericError didn't happen")

  def testRaiseInnerWithMsg(self):
    retry_arg="my_important_debugging_message"
    try:
      try:
        utils.Retry(self._RaiseRetryAgainWithArg, 0.01, 0.02,
                    args=[[retry_arg, retry_arg]],
                    wait_fn = self._wait_fn, _time_fn = self._time_fn)
      except utils.RetryTimeout, err:
        err.RaiseInner()
      else:
        self.fail("Expected timeout didn't happen")
    except utils.RetryTimeout, err:
      self.failUnlessEqual(err.args, (retry_arg, retry_arg))
    else:
      self.fail("Expected RetryTimeout didn't happen")

  def testSimpleRetry(self):
    self.assertFalse(utils.SimpleRetry(True, lambda: False, 0.01, 0.02,
                                       wait_fn = self._wait_fn,
                                       _time_fn = self._time_fn))
    self.assertFalse(utils.SimpleRetry(lambda x: x, lambda: False, 0.01, 0.02,
                                       wait_fn = self._wait_fn,
                                       _time_fn = self._time_fn))
    self.assertTrue(utils.SimpleRetry(True, lambda: True, 0, 1,
                                      wait_fn = self._wait_fn,
                                      _time_fn = self._time_fn))
    self.assertTrue(utils.SimpleRetry(lambda x: x, lambda: True, 0, 1,
                                      wait_fn = self._wait_fn,
                                      _time_fn = self._time_fn))
    self.assertTrue(utils.SimpleRetry(True, self._SimpleRetryAndSucceed, 0, 1,
                                      args=[1], wait_fn = self._wait_fn,
                                      _time_fn = self._time_fn))
    self.assertEqual(self.retries, 1)
    self.assertEqual(self.called, 2)
    self.called = self.retries = 0
    self.assertTrue(utils.SimpleRetry(True, self._SimpleRetryAndSucceed, 0, 1,
                                      args=[2], wait_fn = self._wait_fn,
                                      _time_fn = self._time_fn))
    self.assertEqual(self.called, 3)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
