#!/usr/bin/python
#

# Copyright (C) 2011 Google Inc.
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


"""Script for testing lock performance"""

import os
import sys
import time
import optparse
import threading
import resource

from ganeti import locking


def ParseOptions():
  """Parses the command line options.

  In case of command line errors, it will show the usage and exit the
  program.

  @return: the options in a tuple

  """
  parser = optparse.OptionParser()
  parser.add_option("-t", dest="thread_count", default=1, type="int",
                    help="Number of threads", metavar="NUM")
  parser.add_option("-d", dest="duration", default=5, type="float",
                    help="Duration", metavar="SECS")

  (opts, args) = parser.parse_args()

  if opts.thread_count < 1:
    parser.error("Number of threads must be at least 1")

  return (opts, args)


class State(object):
  def __init__(self, thread_count):
    """Initializes this class.

    """
    self.verify = [0 for _ in range(thread_count)]
    self.counts = [0 for _ in range(thread_count)]
    self.total_count = 0


def _Counter(lock, state, me):
  """Thread function for acquiring locks.

  """
  counts = state.counts
  verify = state.verify

  while True:
    lock.acquire()
    try:
      verify[me] = 1

      counts[me] += 1

      state.total_count += 1

      if state.total_count % 1000 == 0:
        sys.stdout.write(" %8d\r" % state.total_count)
        sys.stdout.flush()

      if sum(verify) != 1:
        print "Inconsistent state!"
        os._exit(1) # pylint: disable=W0212

      verify[me] = 0
    finally:
      lock.release()


def main():
  (opts, _) = ParseOptions()

  lock = locking.SharedLock("TestLock")

  state = State(opts.thread_count)

  lock.acquire(shared=0)
  try:
    for i in range(opts.thread_count):
      t = threading.Thread(target=_Counter, args=(lock, state, i))
      t.setDaemon(True)
      t.start()

    start = time.clock()
  finally:
    lock.release()

  while True:
    if (time.clock() - start) > opts.duration:
      break
    time.sleep(0.1)

  # Make sure we get a consistent view
  lock.acquire(shared=0)

  lock_cputime = time.clock() - start

  res = resource.getrusage(resource.RUSAGE_SELF)

  print "Total number of acquisitions: %s" % state.total_count
  print "Per-thread acquisitions:"
  for (i, count) in enumerate(state.counts):
    print ("  Thread %s: %d (%0.1f%%)" %
           (i, count, (100.0 * count / state.total_count)))

  print "Benchmark CPU time: %0.3fs" % lock_cputime
  print ("Average time per lock acquisition: %0.5fms" %
         (1000.0 * lock_cputime / state.total_count))
  print "Process:"
  print "  User time: %0.3fs" % res.ru_utime
  print "  System time: %0.3fs" % res.ru_stime
  print "  Total time: %0.3fs" % (res.ru_utime + res.ru_stime)

  # Exit directly without attempting to clean up threads
  os._exit(0) # pylint: disable=W0212


if __name__ == "__main__":
  main()
