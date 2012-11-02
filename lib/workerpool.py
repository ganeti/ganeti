#
#

# Copyright (C) 2008, 2009, 2010 Google Inc.
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

import logging
import threading
import heapq

from ganeti import compat
from ganeti import errors


_TERMINATE = object()
_DEFAULT_PRIORITY = 0


class DeferTask(Exception):
  """Special exception class to defer a task.

  This class can be raised by L{BaseWorker.RunTask} to defer the execution of a
  task. Optionally, the priority of the task can be changed.

  """
  def __init__(self, priority=None):
    """Initializes this class.

    @type priority: number
    @param priority: New task priority (None means no change)

    """
    Exception.__init__(self)
    self.priority = priority


class BaseWorker(threading.Thread, object):
  """Base worker class for worker pools.

  Users of a worker pool must override RunTask in a subclass.

  """
  # pylint: disable=W0212
  def __init__(self, pool, worker_id):
    """Constructor for BaseWorker thread.

    @param pool: the parent worker pool
    @param worker_id: identifier for this worker

    """
    super(BaseWorker, self).__init__(name=worker_id)
    self.pool = pool
    self._worker_id = worker_id
    self._current_task = None

    assert self.getName() == worker_id

  def ShouldTerminate(self):
    """Returns whether this worker should terminate.

    Should only be called from within L{RunTask}.

    """
    self.pool._lock.acquire()
    try:
      assert self._HasRunningTaskUnlocked()
      return self.pool._ShouldWorkerTerminateUnlocked(self)
    finally:
      self.pool._lock.release()

  def GetCurrentPriority(self):
    """Returns the priority of the current task.

    Should only be called from within L{RunTask}.

    """
    self.pool._lock.acquire()
    try:
      assert self._HasRunningTaskUnlocked()

      (priority, _, _) = self._current_task

      return priority
    finally:
      self.pool._lock.release()

  def SetTaskName(self, taskname):
    """Sets the name of the current task.

    Should only be called from within L{RunTask}.

    @type taskname: string
    @param taskname: Task's name

    """
    if taskname:
      name = "%s/%s" % (self._worker_id, taskname)
    else:
      name = self._worker_id

    # Set thread name
    self.setName(name)

  def _HasRunningTaskUnlocked(self):
    """Returns whether this worker is currently running a task.

    """
    return (self._current_task is not None)

  def run(self):
    """Main thread function.

    Waits for new tasks to show up in the queue.

    """
    pool = self.pool

    while True:
      assert self._current_task is None

      defer = None
      try:
        # Wait on lock to be told either to terminate or to do a task
        pool._lock.acquire()
        try:
          task = pool._WaitForTaskUnlocked(self)

          if task is _TERMINATE:
            # Told to terminate
            break

          if task is None:
            # Spurious notification, ignore
            continue

          self._current_task = task

          # No longer needed, dispose of reference
          del task

          assert self._HasRunningTaskUnlocked()

        finally:
          pool._lock.release()

        (priority, _, args) = self._current_task
        try:
          # Run the actual task
          assert defer is None
          logging.debug("Starting task %r, priority %s", args, priority)
          assert self.getName() == self._worker_id
          try:
            self.RunTask(*args) # pylint: disable=W0142
          finally:
            self.SetTaskName(None)
          logging.debug("Done with task %r, priority %s", args, priority)
        except DeferTask, err:
          defer = err

          if defer.priority is None:
            # Use same priority
            defer.priority = priority

          logging.debug("Deferring task %r, new priority %s",
                        args, defer.priority)

          assert self._HasRunningTaskUnlocked()
        except: # pylint: disable=W0702
          logging.exception("Caught unhandled exception")

        assert self._HasRunningTaskUnlocked()
      finally:
        # Notify pool
        pool._lock.acquire()
        try:
          if defer:
            assert self._current_task
            # Schedule again for later run
            (_, _, args) = self._current_task
            pool._AddTaskUnlocked(args, defer.priority)

          if self._current_task:
            self._current_task = None
            pool._worker_to_pool.notifyAll()
        finally:
          pool._lock.release()

      assert not self._HasRunningTaskUnlocked()

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
    self._active = True

    # Terminating workers
    self._termworkers = []

    # Queued tasks
    self._counter = 0
    self._tasks = []

    # Start workers
    self.Resize(num_workers)

  # TODO: Implement dynamic resizing?

  def _WaitWhileQuiescingUnlocked(self):
    """Wait until the worker pool has finished quiescing.

    """
    while self._quiescing:
      self._pool_to_pool.wait()

  def _AddTaskUnlocked(self, args, priority):
    """Adds a task to the internal queue.

    @type args: sequence
    @param args: Arguments passed to L{BaseWorker.RunTask}
    @type priority: number
    @param priority: Task priority

    """
    assert isinstance(args, (tuple, list)), "Arguments must be a sequence"
    assert isinstance(priority, (int, long)), "Priority must be numeric"

    # This counter is used to ensure elements are processed in their
    # incoming order. For processing they're sorted by priority and then
    # counter.
    self._counter += 1

    heapq.heappush(self._tasks, (priority, self._counter, args))

    # Notify a waiting worker
    self._pool_to_worker.notify()

  def AddTask(self, args, priority=_DEFAULT_PRIORITY):
    """Adds a task to the queue.

    @type args: sequence
    @param args: arguments passed to L{BaseWorker.RunTask}
    @type priority: number
    @param priority: Task priority

    """
    self._lock.acquire()
    try:
      self._WaitWhileQuiescingUnlocked()
      self._AddTaskUnlocked(args, priority)
    finally:
      self._lock.release()

  def AddManyTasks(self, tasks, priority=_DEFAULT_PRIORITY):
    """Add a list of tasks to the queue.

    @type tasks: list of tuples
    @param tasks: list of args passed to L{BaseWorker.RunTask}
    @type priority: number or list of numbers
    @param priority: Priority for all added tasks or a list with the priority
                     for each task

    """
    assert compat.all(isinstance(task, (tuple, list)) for task in tasks), \
      "Each task must be a sequence"

    assert (isinstance(priority, (int, long)) or
            compat.all(isinstance(prio, (int, long)) for prio in priority)), \
           "Priority must be numeric or be a list of numeric values"

    if isinstance(priority, (int, long)):
      priority = [priority] * len(tasks)
    elif len(priority) != len(tasks):
      raise errors.ProgrammerError("Number of priorities (%s) doesn't match"
                                   " number of tasks (%s)" %
                                   (len(priority), len(tasks)))

    self._lock.acquire()
    try:
      self._WaitWhileQuiescingUnlocked()

      assert compat.all(isinstance(prio, (int, long)) for prio in priority)
      assert len(tasks) == len(priority)

      for args, prio in zip(tasks, priority):
        self._AddTaskUnlocked(args, prio)
    finally:
      self._lock.release()

  def SetActive(self, active):
    """Enable/disable processing of tasks.

    This is different from L{Quiesce} in the sense that this function just
    changes an internal flag and doesn't wait for the queue to be empty. Tasks
    already being processed continue normally, but no new tasks will be
    started. New tasks can still be added.

    @type active: bool
    @param active: Whether tasks should be processed

    """
    self._lock.acquire()
    try:
      self._active = active

      if active:
        # Tell all workers to continue processing
        self._pool_to_worker.notifyAll()
    finally:
      self._lock.release()

  def _WaitForTaskUnlocked(self, worker):
    """Waits for a task for a worker.

    @type worker: L{BaseWorker}
    @param worker: Worker thread

    """
    while True:
      if self._ShouldWorkerTerminateUnlocked(worker):
        return _TERMINATE

      # If there's a pending task, return it immediately
      if self._active and self._tasks:
        # Get task from queue and tell pool about it
        try:
          task = heapq.heappop(self._tasks)
        finally:
          self._worker_to_pool.notifyAll()

        return task

      logging.debug("Waiting for tasks")

      # wait() releases the lock and sleeps until notified
      self._pool_to_worker.wait()

      logging.debug("Notified while waiting")

  def _ShouldWorkerTerminateUnlocked(self, worker):
    """Returns whether a worker should terminate.

    """
    return (worker in self._termworkers)

  def _HasRunningTasksUnlocked(self):
    """Checks whether there's a task running in a worker.

    """
    for worker in self._workers + self._termworkers:
      if worker._HasRunningTaskUnlocked(): # pylint: disable=W0212
        return True
    return False

  def HasRunningTasks(self):
    """Checks whether there's at least one task running.

    """
    self._lock.acquire()
    try:
      return self._HasRunningTasksUnlocked()
    finally:
      self._lock.release()

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
