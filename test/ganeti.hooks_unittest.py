#!/usr/bin/python
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


"""Script for unittesting the hooks module"""


import unittest
import os
import time
import tempfile
import os.path

from ganeti import errors
from ganeti import opcodes
from ganeti import mcpu
from ganeti import backend
from ganeti import constants
from ganeti import cmdlib
from ganeti import rpc
from ganeti.constants import HKR_SUCCESS, HKR_FAIL, HKR_SKIP

from mocks import FakeConfig, FakeProc, FakeContext

class FakeLU(cmdlib.LogicalUnit):
  HPATH = "test"
  def BuildHooksEnv(self):
    return {}, ["localhost"], ["localhost"]

class TestHooksRunner(unittest.TestCase):
  """Testing case for HooksRunner"""
  def setUp(self):
    self.torm = []
    self.tmpdir = tempfile.mkdtemp()
    self.torm.append((self.tmpdir, True))
    self.logdir = tempfile.mkdtemp()
    self.torm.append((self.logdir, True))
    self.hpath = "fake"
    self.ph_dirs = {}
    for i in (constants.HOOKS_PHASE_PRE, constants.HOOKS_PHASE_POST):
      dname = "%s/%s-%s.d" % (self.tmpdir, self.hpath, i)
      os.mkdir(dname)
      self.torm.append((dname, True))
      self.ph_dirs[i] = dname
    self.hr = backend.HooksRunner(hooks_base_dir=self.tmpdir)

  def tearDown(self):
    self.torm.reverse()
    for path, kind in self.torm:
      if kind:
        os.rmdir(path)
      else:
        os.unlink(path)

  def _rname(self, fname):
    return "/".join(fname.split("/")[-2:])

  def testEmpty(self):
    """Test no hooks"""
    for phase in (constants.HOOKS_PHASE_PRE, constants.HOOKS_PHASE_POST):
      self.failUnlessEqual(self.hr.RunHooks(self.hpath, phase, {}), [])

  def testSkipNonExec(self):
    """Test skip non-exec file"""
    for phase in (constants.HOOKS_PHASE_PRE, constants.HOOKS_PHASE_POST):
      fname = "%s/test" % self.ph_dirs[phase]
      f = open(fname, "w")
      f.close()
      self.torm.append((fname, False))
      self.failUnlessEqual(self.hr.RunHooks(self.hpath, phase, {}),
                           [(self._rname(fname), HKR_SKIP, "")])

  def testSkipInvalidName(self):
    """Test skip script with invalid name"""
    for phase in (constants.HOOKS_PHASE_PRE, constants.HOOKS_PHASE_POST):
      fname = "%s/a.off" % self.ph_dirs[phase]
      f = open(fname, "w")
      f.write("#!/bin/sh\nexit 0\n")
      f.close()
      os.chmod(fname, 0700)
      self.torm.append((fname, False))
      self.failUnlessEqual(self.hr.RunHooks(self.hpath, phase, {}),
                           [(self._rname(fname), HKR_SKIP, "")])

  def testSkipDir(self):
    """Test skip directory"""
    for phase in (constants.HOOKS_PHASE_PRE, constants.HOOKS_PHASE_POST):
      fname = "%s/testdir" % self.ph_dirs[phase]
      os.mkdir(fname)
      self.torm.append((fname, True))
      self.failUnlessEqual(self.hr.RunHooks(self.hpath, phase, {}),
                           [(self._rname(fname), HKR_SKIP, "")])

  def testSuccess(self):
    """Test success execution"""
    for phase in (constants.HOOKS_PHASE_PRE, constants.HOOKS_PHASE_POST):
      fname = "%s/success" % self.ph_dirs[phase]
      f = open(fname, "w")
      f.write("#!/bin/sh\nexit 0\n")
      f.close()
      self.torm.append((fname, False))
      os.chmod(fname, 0700)
      self.failUnlessEqual(self.hr.RunHooks(self.hpath, phase, {}),
                           [(self._rname(fname), HKR_SUCCESS, "")])

  def testSymlink(self):
    """Test running a symlink"""
    for phase in (constants.HOOKS_PHASE_PRE, constants.HOOKS_PHASE_POST):
      fname = "%s/success" % self.ph_dirs[phase]
      os.symlink("/bin/true", fname)
      self.torm.append((fname, False))
      self.failUnlessEqual(self.hr.RunHooks(self.hpath, phase, {}),
                           [(self._rname(fname), HKR_SUCCESS, "")])

  def testFail(self):
    """Test success execution"""
    for phase in (constants.HOOKS_PHASE_PRE, constants.HOOKS_PHASE_POST):
      fname = "%s/success" % self.ph_dirs[phase]
      f = open(fname, "w")
      f.write("#!/bin/sh\nexit 1\n")
      f.close()
      self.torm.append((fname, False))
      os.chmod(fname, 0700)
      self.failUnlessEqual(self.hr.RunHooks(self.hpath, phase, {}),
                           [(self._rname(fname), HKR_FAIL, "")])

  def testCombined(self):
    """Test success, failure and skip all in one test"""
    for phase in (constants.HOOKS_PHASE_PRE, constants.HOOKS_PHASE_POST):
      expect = []
      for fbase, ecode, rs in [("00succ", 0, HKR_SUCCESS),
                               ("10fail", 1, HKR_FAIL),
                               ("20inv.", 0, HKR_SKIP),
                               ]:
        fname = "%s/%s" % (self.ph_dirs[phase], fbase)
        f = open(fname, "w")
        f.write("#!/bin/sh\nexit %d\n" % ecode)
        f.close()
        self.torm.append((fname, False))
        os.chmod(fname, 0700)
        expect.append((self._rname(fname), rs, ""))
      self.failUnlessEqual(self.hr.RunHooks(self.hpath, phase, {}), expect)

  def testOrdering(self):
    for phase in (constants.HOOKS_PHASE_PRE, constants.HOOKS_PHASE_POST):
      expect = []
      for fbase in ["10s1",
                    "00s0",
                    "10sa",
                    "80sc",
                    "60sd",
                    ]:
        fname = "%s/%s" % (self.ph_dirs[phase], fbase)
        os.symlink("/bin/true", fname)
        self.torm.append((fname, False))
        expect.append((self._rname(fname), HKR_SUCCESS, ""))
      expect.sort()
      self.failUnlessEqual(self.hr.RunHooks(self.hpath, phase, {}), expect)

  def testEnv(self):
    """Test environment execution"""
    for phase in (constants.HOOKS_PHASE_PRE, constants.HOOKS_PHASE_POST):
      fbase = "success"
      fname = "%s/%s" % (self.ph_dirs[phase], fbase)
      os.symlink("/usr/bin/env", fname)
      self.torm.append((fname, False))
      env_snt = {"PHASE": phase}
      env_exp = "PHASE=%s\n" % phase
      self.failUnlessEqual(self.hr.RunHooks(self.hpath, phase, env_snt),
                           [(self._rname(fname), HKR_SUCCESS, env_exp)])


class TestHooksMaster(unittest.TestCase):
  """Testing case for HooksMaster"""

  def _call_false(*args):
    """Fake call_hooks_runner function which returns False."""
    return False

  @staticmethod
  def _call_nodes_false(node_list, hpath, phase, env):
    """Fake call_hooks_runner function.

    @rtype: dict of node -> L{rpc.RpcResult} with an rpc error
    @return: rpc failure from all nodes

    """
    return dict([(node, rpc.RpcResult('error', failed=True,
                  node=node, call='FakeError')) for node in node_list])

  @staticmethod
  def _call_script_fail(node_list, hpath, phase, env):
    """Fake call_hooks_runner function.

    @rtype: dict of node -> L{rpc.RpcResult} with a failed script result
    @return: script execution failure from all nodes

    """
    return dict([(node, rpc.RpcResult([("utest", constants.HKR_FAIL, "err")],
                  node=node, call='FakeScriptFail')) for node in node_list])

  @staticmethod
  def _call_script_succeed(node_list, hpath, phase, env):
    """Fake call_hooks_runner function.

    @rtype: dict of node -> L{rpc.RpcResult} with a successful script result
    @return: script execution from all nodes

    """
    return dict([(node, rpc.RpcResult([("utest", constants.HKR_SUCCESS, "ok")],
                  node=node, call='FakeScriptOk')) for node in node_list])

  def setUp(self):
    self.op = opcodes.OpCode()
    self.context = FakeContext()
    # WARNING: here we pass None as RpcRunner instance since we know
    # our usage via HooksMaster will not use lu.rpc
    self.lu = FakeLU(FakeProc(), self.op, self.context, None)

  def testTotalFalse(self):
    """Test complete rpc failure"""
    hm = mcpu.HooksMaster(self._call_false, FakeProc(), self.lu)
    self.failUnlessRaises(errors.HooksFailure,
                          hm.RunPhase, constants.HOOKS_PHASE_PRE)
    hm.RunPhase(constants.HOOKS_PHASE_POST)

  def testIndividualFalse(self):
    """Test individual node failure"""
    hm = mcpu.HooksMaster(self._call_nodes_false, FakeProc(), self.lu)
    hm.RunPhase(constants.HOOKS_PHASE_PRE)
    #self.failUnlessRaises(errors.HooksFailure,
    #                      hm.RunPhase, constants.HOOKS_PHASE_PRE)
    hm.RunPhase(constants.HOOKS_PHASE_POST)

  def testScriptFalse(self):
    """Test individual rpc failure"""
    hm = mcpu.HooksMaster(self._call_script_fail, FakeProc(), self.lu)
    self.failUnlessRaises(errors.HooksAbort,
                          hm.RunPhase, constants.HOOKS_PHASE_PRE)
    hm.RunPhase(constants.HOOKS_PHASE_POST)

  def testScriptSucceed(self):
    """Test individual rpc failure"""
    hm = mcpu.HooksMaster(self._call_script_succeed, FakeProc(), self.lu)
    for phase in (constants.HOOKS_PHASE_PRE, constants.HOOKS_PHASE_POST):
      hm.RunPhase(phase)

if __name__ == '__main__':
  unittest.main()
