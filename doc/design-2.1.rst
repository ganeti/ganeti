=================
Ganeti 2.1 design
=================

This document describes the major changes in Ganeti 2.1 compared to
the 2.0 version.

The 2.1 version will be a relatively small release. Its main aim is to avoid
changing too much of the core code, while addressing issues and adding new
features and improvements over 2.0, in a timely fashion.

.. contents:: :depth: 3

Objective
=========

Ganeti 2.1 will add features to help further automatization of cluster
operations, further improbe scalability to even bigger clusters, and make it
easier to debug the Ganeti core.

Background
==========

Overview
========

Detailed design
===============

As for 2.0 we divide the 2.1 design into three areas:

- core changes, which affect the master daemon/job queue/locking or all/most
  logical units
- logical unit/feature changes
- external interface changes (eg. command line, os api, hooks, ...)

Core changes
------------

Feature changes
---------------

External interface changes
--------------------------

