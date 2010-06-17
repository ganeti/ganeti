#
#

# Copyright (C) 2008 Google Inc.
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


"""Base classes for worker pools.

"""

import collections
import logging
import threading

from ganeti import compat


class BaseWorker(threading.Thread, object):
  """Base worker class for worker pools.

  Users of a worker pool must override RunTask in a subclass.

  """
  # pylint: disable-msg=W0212
  def __init__(self, pool, worker_id):
    """Constructor for BaseWorker thread.

    @param pool: the parent worker pool
    @param worker_id: identifier for this worker

    """
    super(BaseWorker, self).__init__(name=worker_id)
    self.pool = pool
    self._current_task = None

  def ShouldTerminate(self):
    """Returns whether a worker should terminate.

    """
    return self.pool.ShouldWorkerTerminate(self)

  def _HasRunningTaskUnlocked(self):
    """Returns whether this worker is currently running a task.

    """
    return (self._current_task is not None)

  def HasRunningTask(self):
    """Returns whether this worker is currently running a task.

    """
    self.pool._lock.acquire()
    try:
      return self._HasRunningTaskUnlocked()
    finally:
      self.pool._lock.release()

  def run(self):
    """Main thread function.

    Waits for new tasks to show up in the queue.

    """
    pool = self.pool

    assert not self.HasRunningTask()

    while True:
      try:
        # We wait on lock to be told either terminate or do a task.
        pool._lock.acquire()
        try:
          if pool._ShouldWorkerTerminateUnlocked(self):
            break

          # We only wait if there's no task for us.
          if not pool._tasks:
            logging.debug("Waiting for tasks")

            # wait() releases the lock and sleeps until notified
            pool._pool_to_worker.wait()

            logging.debug("Notified while waiting")

            # Were we woken up in order to terminate?
            if pool._ShouldWorkerTerminateUnlocked(self):
              break

            if not pool._tasks:
              # Spurious notification, ignore
              continue

          # Get task from queue and tell pool about it
          try:
            self._current_task = pool._tasks.popleft()
          finally:
            pool._worker_to_pool.notifyAll()
        finally:
          pool._lock.release()

        # Run the actual task
        try:
          logging.debug("Starting task %r", self._current_task)
          self.RunTask(*self._current_task)
          logging.debug("Done with task %r", self._current_task)
        except: # pylint: disable-msg=W0702
          logging.exception("Caught unhandled exception")
      finally:
        # Notify pool
        pool._lock.acquire()
        try:
          if self._current_task:
            self._current_task = None
            pool._worker_to_pool.notifyAll()
        finally:
          pool._lock.release()

    logging.debug("Terminates")

  def RunTask(self, *args):
    """Function called to start a task.

    This needs to be implemented by child classes.

    """
    raise NotImplementedError()


class WorkerPool(object):
  """Worker pool with a queue.

  This class is thread-safe.

  Tasks are guaranteed to be started in the order in which they're
  added to the pool. Due to the nature of threading, they're not
  guaranteed to finish in the same order.

  """
  def __init__(self, name, num_workers, worker_class):
    """Constructor for worker pool.

    @param num_workers: number of workers to be started
        (dynamic resizing is not yet implemented)
    @param worker_class: the class to be instantiated for workers;
        should derive from L{BaseWorker}

    """
    # Some of these variables are accessed by BaseWorker
    self._lock = threading.Lock()
    self._pool_to_pool = threading.Condition(self._lock)
    self._pool_to_worker = threading.Condition(self._lock)
    self._worker_to_pool = threading.Condition(self._lock)
    self._worker_class = worker_class
    self._name = name
    self._last_worker_id = 0
    self._workers = []
    self._quiescing = False

    # Terminating workers
    self._termworkers = []

    # Queued tasks
    self._tasks = collections.deque()

    # Start workers
    self.Resize(num_workers)

  # TODO: Implement dynamic resizing?

  def _WaitWhileQuiescingUnlocked(self):
    """Wait until the worker pool has finished quiescing.

    """
    while self._quiescing:
      self._pool_to_pool.wait()

  def AddTask(self, *args):
    """Adds a task to the queue.

    @param args: arguments passed to L{BaseWorker.RunTask}

    """
    self._lock.acquire()
    try:
      self._WaitWhileQuiescingUnlocked()

      self._tasks.append(args)

      # Wake one idling worker up
      self._pool_to_worker.notify()
    finally:
      self._lock.release()

  def AddManyTasks(self, tasks):
    """Add a list of tasks to the queue.

    @type tasks: list of tuples
    @param tasks: list of args passed to L{BaseWorker.RunTask}

    """
    assert compat.all(isinstance(task, (tuple, list)) for task in tasks), \
      "Each task must be a sequence"

    self._lock.acquire()
    try:
      self._WaitWhileQuiescingUnlocked()

      self._tasks.extend(tasks)

      for _ in tasks:
        self._pool_to_worker.notify()
    finally:
      self._lock.release()

  def _ShouldWorkerTerminateUnlocked(self, worker):
    """Returns whether a worker should terminate.

    """
    return (worker in self._termworkers)

  def ShouldWorkerTerminate(self, worker):
    """Returns whether a worker should terminate.

    """
    self._lock.acquire()
    try:
      return self._ShouldWorkerTerminateUnlocked(worker)
    finally:
      self._lock.release()

  def _HasRunningTasksUnlocked(self):
    """Checks whether there's a task running in a worker.

    """
    for worker in self._workers + self._termworkers:
      if worker._HasRunningTaskUnlocked(): # pylint: disable-msg=W0212
        return True
    return False

  def Quiesce(self):
    """Waits until the task queue is empty.

    """
    self._lock.acquire()
    try:
      self._quiescing = True

      # Wait while there are tasks pending or running
      while self._tasks or self._HasRunningTasksUnlocked():
        self._worker_to_pool.wait()

    finally:
      self._quiescing = False

      # Make sure AddTasks continues in case it was waiting
      self._pool_to_pool.notifyAll()

      self._lock.release()

  def _NewWorkerIdUnlocked(self):
    """Return an identifier for a new worker.

    """
    self._last_worker_id += 1

    return "%s%d" % (self._name, self._last_worker_id)

  def _ResizeUnlocked(self, num_workers):
    """Changes the number of workers.

    """
    assert num_workers >= 0, "num_workers must be >= 0"

    logging.debug("Resizing to %s workers", num_workers)

    current_count = len(self._workers)

    if current_count == num_workers:
      # Nothing to do
      pass

    elif current_count > num_workers:
      if num_workers == 0:
        # Create copy of list to iterate over while lock isn't held.
        termworkers = self._workers[:]
        del self._workers[:]
      else:
        # TODO: Implement partial downsizing
        raise NotImplementedError()
        #termworkers = ...

      self._termworkers += termworkers

      # Notify workers that something has changed
      self._pool_to_worker.notifyAll()

      # Join all terminating workers
      self._lock.release()
      try:
        for worker in termworkers:
          logging.debug("Waiting for thread %s", worker.getName())
          worker.join()
      finally:
        self._lock.acquire()

      # Remove terminated threads. This could be done in a more efficient way
      # (del self._termworkers[:]), but checking worker.isAlive() makes sure we
      # don't leave zombie threads around.
      for worker in termworkers:
        assert worker in self._termworkers, ("Worker not in list of"
                                             " terminating workers")
        if not worker.isAlive():
          self._termworkers.remove(worker)

      assert not self._termworkers, "Zombie worker detected"

    elif current_count < num_workers:
      # Create (num_workers - current_count) new workers
      for _ in range(num_workers - current_count):
        worker = self._worker_class(self, self._NewWorkerIdUnlocked())
        self._workers.append(worker)
        worker.start()

  def Resize(self, num_workers):
    """Changes the number of workers in the pool.

    @param num_workers: the new number of workers

    """
    self._lock.acquire()
    try:
      return self._ResizeUnlocked(num_workers)
    finally:
      self._lock.release()

  def TerminateWorkers(self):
    """Terminate all worker threads.

    Unstarted tasks will be ignored.

    """
    logging.debug("Terminating all workers")

    self._lock.acquire()
    try:
      self._ResizeUnlocked(0)

      if self._tasks:
        logging.debug("There are %s tasks left", len(self._tasks))
    finally:
      self._lock.release()

    logging.debug("All workers terminated")
