#
#

# Copyright (C) 2008, 2009, 2010 Google Inc.
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


"""Base classes for worker pools.

"""

import logging
import threading
import heapq
import itertools

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


class NoSuchTask(Exception):
  """Exception raised when a task can't be found.

  """


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

      (priority, _, _, _) = self._current_task

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

  def _GetCurrentOrderAndTaskId(self):
    """Returns the order and task ID of the current task.

    Should only be called from within L{RunTask}.

    """
    self.pool._lock.acquire()
    try:
      assert self._HasRunningTaskUnlocked()

      (_, order_id, task_id, _) = self._current_task

      return (order_id, task_id)
    finally:
      self.pool._lock.release()

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

        (priority, _, _, args) = self._current_task
        try:
          # Run the actual task
          assert defer is None
          logging.debug("Starting task %r, priority %s", args, priority)
          assert self.getName() == self._worker_id
          try:
            self.RunTask(*args)
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
            (_, _, task_id, args) = self._current_task
            pool._AddTaskUnlocked(args, defer.priority, task_id)

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

  @type _tasks: list of tuples
  @ivar _tasks: Each tuple has the format (priority, order ID, task ID,
    arguments). Priority and order ID are numeric and essentially control the
    sort order. The order ID is an increasing number denoting the order in
    which tasks are added to the queue. The task ID is controlled by user of
    workerpool, see L{AddTask} for details. The task arguments are C{None} for
    abandoned tasks, otherwise a sequence of arguments to be passed to
    L{BaseWorker.RunTask}). The list must fulfill the heap property (for use by
    the C{heapq} module).
  @type _taskdata: dict; (task IDs as keys, tuples as values)
  @ivar _taskdata: Mapping from task IDs to entries in L{_tasks}

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
    self._counter = itertools.count()
    self._tasks = []
    self._taskdata = {}

    # Start workers
    self.Resize(num_workers)

  # TODO: Implement dynamic resizing?

  def _WaitWhileQuiescingUnlocked(self):
    """Wait until the worker pool has finished quiescing.

    """
    while self._quiescing:
      self._pool_to_pool.wait()

  def _AddTaskUnlocked(self, args, priority, task_id):
    """Adds a task to the internal queue.

    @type args: sequence
    @param args: Arguments passed to L{BaseWorker.RunTask}
    @type priority: number
    @param priority: Task priority
    @param task_id: Task ID

    """
    assert isinstance(args, (tuple, list)), "Arguments must be a sequence"
    assert isinstance(priority, (int, long)), "Priority must be numeric"
    assert task_id is None or isinstance(task_id, (int, long)), \
      "Task ID must be numeric or None"

    task = [priority, self._counter.next(), task_id, args]

    if task_id is not None:
      assert task_id not in self._taskdata
      # Keep a reference to change priority later if necessary
      self._taskdata[task_id] = task

    # A counter is used to ensure elements are processed in their incoming
    # order. For processing they're sorted by priority and then counter.
    heapq.heappush(self._tasks, task)

    # Notify a waiting worker
    self._pool_to_worker.notify()

  def AddTask(self, args, priority=_DEFAULT_PRIORITY, task_id=None):
    """Adds a task to the queue.

    @type args: sequence
    @param args: arguments passed to L{BaseWorker.RunTask}
    @type priority: number
    @param priority: Task priority
    @param task_id: Task ID
    @note: The task ID can be essentially anything that can be used as a
      dictionary key. Callers, however, must ensure a task ID is unique while a
      task is in the pool or while it might return to the pool due to deferring
      using L{DeferTask}.

    """
    self._lock.acquire()
    try:
      self._WaitWhileQuiescingUnlocked()
      self._AddTaskUnlocked(args, priority, task_id)
    finally:
      self._lock.release()

  def AddManyTasks(self, tasks, priority=_DEFAULT_PRIORITY, task_id=None):
    """Add a list of tasks to the queue.

    @type tasks: list of tuples
    @param tasks: list of args passed to L{BaseWorker.RunTask}
    @type priority: number or list of numbers
    @param priority: Priority for all added tasks or a list with the priority
                     for each task
    @type task_id: list
    @param task_id: List with the ID for each task
    @note: See L{AddTask} for a note on task IDs.

    """
    assert compat.all(isinstance(task, (tuple, list)) for task in tasks), \
           "Each task must be a sequence"
    assert (isinstance(priority, (int, long)) or
            compat.all(isinstance(prio, (int, long)) for prio in priority)), \
           "Priority must be numeric or be a list of numeric values"
    assert task_id is None or isinstance(task_id, (tuple, list)), \
           "Task IDs must be in a sequence"

    if isinstance(priority, (int, long)):
      priority = [priority] * len(tasks)
    elif len(priority) != len(tasks):
      raise errors.ProgrammerError("Number of priorities (%s) doesn't match"
                                   " number of tasks (%s)" %
                                   (len(priority), len(tasks)))

    if task_id is None:
      task_id = [None] * len(tasks)
    elif len(task_id) != len(tasks):
      raise errors.ProgrammerError("Number of task IDs (%s) doesn't match"
                                   " number of tasks (%s)" %
                                   (len(task_id), len(tasks)))

    self._lock.acquire()
    try:
      self._WaitWhileQuiescingUnlocked()

      assert compat.all(isinstance(prio, (int, long)) for prio in priority)
      assert len(tasks) == len(priority)
      assert len(tasks) == len(task_id)

      for (args, prio, tid) in zip(tasks, priority, task_id):
        self._AddTaskUnlocked(args, prio, tid)
    finally:
      self._lock.release()

  def ChangeTaskPriority(self, task_id, priority):
    """Changes a task's priority.

    @param task_id: Task ID
    @type priority: number
    @param priority: New task priority
    @raise NoSuchTask: When the task referred by C{task_id} can not be found
      (it may never have existed, may have already been processed, or is
      currently running)

    """
    assert isinstance(priority, (int, long)), "Priority must be numeric"

    self._lock.acquire()
    try:
      logging.debug("About to change priority of task %s to %s",
                    task_id, priority)

      # Find old task
      oldtask = self._taskdata.get(task_id, None)
      if oldtask is None:
        msg = "Task '%s' was not found" % task_id
        logging.debug(msg)
        raise NoSuchTask(msg)

      # Prepare new task
      newtask = [priority] + oldtask[1:]

      # Mark old entry as abandoned (this doesn't change the sort order and
      # therefore doesn't invalidate the heap property of L{self._tasks}).
      # See also <http://docs.python.org/library/heapq.html#priority-queue-
      # implementation-notes>.
      oldtask[-1] = None

      # Change reference to new task entry and forget the old one
      assert task_id is not None
      self._taskdata[task_id] = newtask

      # Add a new task with the old number and arguments
      heapq.heappush(self._tasks, newtask)

      # Notify a waiting worker
      self._pool_to_worker.notify()
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
      if self._tasks:
        # Get task from queue and tell pool about it
        try:
          task = heapq.heappop(self._tasks)
        finally:
          self._worker_to_pool.notifyAll()

        (_, _, task_id, args) = task

        # If the priority was changed, "args" is None
        if args is None:
          # Try again
          logging.debug("Found abandoned task (%r)", task)
          continue

        # Delete reference
        if task_id is not None:
          del self._taskdata[task_id]

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
