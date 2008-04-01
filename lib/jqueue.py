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


"""Module implementing the job queue handling."""

import threading
import Queue

from ganeti import opcodes

class JobObject:
  """In-memory job representation.

  This is what we use to track the user-submitted jobs (which are of
  class opcodes.Job).

  """
  def __init__(self, jid, jdesc):
    self.data = jdesc
    jdesc.status = opcodes.Job.STATUS_PENDING
    jdesc.job_id = jid
    self.lock = threading.Lock()

  def SetStatus(self, status, result=None):
    self.lock.acquire()
    self.data.status = status
    if result is not None:
      self.data.result = result
    self.lock.release()

  def GetData(self):
    self.lock.acquire()
    #FIXME(iustin): make a deep copy of result
    result = self.data
    self.lock.release()
    return result


class QueueManager:
  """Example queue implementation.

  """
  def __init__(self):
    self.job_queue = {}
    self.jid = 1
    self.lock = threading.Lock()
    self.new_queue = Queue.Queue()

  def put(self, item):
    """Add a new job to the queue.

    This enters the job into our job queue and also puts it on the new
    queue, in order for it to be picked up by the queue processors.

    """
    self.lock.acquire()
    try:
      rid = self.jid
      self.jid += 1
      job = JobObject(rid, item)
      self.job_queue[rid] = job
    finally:
      self.lock.release()
    self.new_queue.put(job)
    return rid

  def query(self, rid):
    """Query a given job ID.

    """
    self.lock.acquire()
    result = self.job_queue.get(rid, None)
    self.lock.release()
    return result
