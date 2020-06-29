=================
Ganeti 3.0 design
=================

This document describes the major changes between Ganeti 2.16 and 3.0.

Objective
=========

All Ganeti versions prior to 3.0 are built on Python 2 code. With Python 3 being the offical default and version 2 slowly fading out of Linux distributions, the goal of this major release is to achieve full and only Python 3 compatibility.

Minimum supported Python version
================================

We require a minimum of Python 3.6 for the current code to work. This allows us to support stable distributions like Debian Buster or Ubuntu 18.04 LTS and to create working upgrade paths for our users.

What happened to Ganeti 2.17?
=============================

A beta version of 2.17 has been released on February 22nd, 2016. This version has not seen exhaustive testing but included a number of new features. To push forward with the migration to Python 3, we decided to ditch these changes and start over based on Ganeti 2.16. Since the upgrade to 2.17.0~beta1 introduced some breaking changes, there is currently no direct upgrade path between 2.17 and 3.0. The only known but untested way is to downgrade to Ganeti 2.16 first and then upgrade to 3.0. This will remove access to incomplete features like the Ganeti Maintenance Daemon.

What other features/changes have been introduced with 3.0?
==========================================================

Since 2.16, a number of bugfixes, compatibility improvements and updates to documentation have been included. Please refer to the release notes for more details. However, no changes to the on-disk data and no breaking changes to commandline tools have been included.